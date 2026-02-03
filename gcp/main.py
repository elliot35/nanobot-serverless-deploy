"""
Google Cloud Run/Functions entry point for nanobot serverless deployment.

This FastAPI application handles Telegram webhooks and provides health checks.
"""

import os
import sys
import json
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../'))

from src.handlers import handle_telegram_webhook_request, handle_health_check_request

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="nanobot Serverless Gateway",
    description="Serverless deployment of nanobot AI assistant",
    version="0.1.0"
)


@app.post("/api/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Handle Telegram webhook POST requests.
    
    Telegram sends updates to this endpoint when messages are received.
    """
    try:
        # Get request body
        body = await request.body()
        body_str = body.decode("utf-8") if isinstance(body, bytes) else body
        
        # Get headers
        headers = dict(request.headers)
        
        # Handle webhook
        response = await handle_telegram_webhook_request(body_str, headers)
        
        return JSONResponse(
            content=json.loads(response["body"]) if isinstance(response["body"], str) else response["body"],
            status_code=response["status_code"],
            headers=response.get("headers", {})
        )
        
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns the status of the gateway and its components.
    """
    try:
        response = await handle_health_check_request()
        
        return JSONResponse(
            content=json.loads(response["body"]) if isinstance(response["body"], str) else response["body"],
            status_code=response["status_code"],
            headers=response.get("headers", {})
        )
        
    except Exception as e:
        logger.error(f"Error in health check: {e}", exc_info=True)
        return JSONResponse(
            content={"status": "unhealthy", "error": str(e)},
            status_code=503
        )


@app.get("/")
async def root():
    """Root endpoint with basic info."""
    return {
        "service": "nanobot-serverless-deploy",
        "status": "running",
        "endpoints": {
            "webhook": "/api/webhook/telegram",
            "health": "/api/health"
        }
    }


if __name__ == "__main__":
    # For local development
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
