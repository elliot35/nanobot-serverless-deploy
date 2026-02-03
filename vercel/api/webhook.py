"""
Vercel serverless function handler for Telegram webhooks.

This function handles POST requests from Telegram webhooks and routes them
to the nanobot gateway adapter.
"""

import json
import os
import sys
import logging
from http.server import BaseHTTPRequestHandler
import asyncio

# Add parent directory to path to import src modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from src.handlers import handle_telegram_webhook_request, handle_health_check_request

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    """
    Vercel serverless function handler using BaseHTTPRequestHandler.
    """
    
    def do_POST(self):
        """Handle POST requests (Telegram webhooks)."""
        if self.path.startswith("/api/webhook"):
            try:
                # Read request body
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                
                # Get headers
                headers = dict(self.headers)
                
                # Handle webhook asynchronously
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    response = loop.run_until_complete(
                        handle_telegram_webhook_request(body, headers)
                    )
                    
                    self.send_response(response["status_code"])
                    for key, value in response.get("headers", {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(response["body"].encode('utf-8'))
                finally:
                    loop.close()
                    
            except Exception as e:
                logger.error(f"Error handling webhook: {e}", exc_info=True)
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Internal server error"}).encode('utf-8'))
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode('utf-8'))
    
    def do_GET(self):
        """Handle GET requests (health check)."""
        if self.path == "/api/health":
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    response = loop.run_until_complete(handle_health_check_request())
                    
                    self.send_response(response["status_code"])
                    for key, value in response.get("headers", {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(response["body"].encode('utf-8'))
                finally:
                    loop.close()
                    
            except Exception as e:
                logger.error(f"Error in health check: {e}", exc_info=True)
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "unhealthy", "error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to use our logger instead of default logging."""
        logger.info("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))
