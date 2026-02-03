"""HTTP request handlers for serverless platforms."""

import json
import logging
from typing import Dict, Any, Optional
from .adapter import handle_telegram_update, get_health_status

logger = logging.getLogger(__name__)


async def handle_telegram_webhook_request(request_body: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Handle a Telegram webhook HTTP request.
    
    Args:
        request_body: Raw request body as string
        headers: Request headers dictionary
        
    Returns:
        Response dictionary with status_code and body
    """
    try:
        # Parse JSON body
        try:
            update = json.loads(request_body)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request body: {e}")
            return {
                "status_code": 400,
                "body": json.dumps({"ok": False, "error": "Invalid JSON"}),
                "headers": {"Content-Type": "application/json"}
            }
        
        # Handle the update
        result = await handle_telegram_update(update)
        
        # Return success response
        return {
            "status_code": 200,
            "body": json.dumps(result),
            "headers": {"Content-Type": "application/json"}
        }
        
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {e}", exc_info=True)
        return {
            "status_code": 500,
            "body": json.dumps({"ok": False, "error": "Internal server error"}),
            "headers": {"Content-Type": "application/json"}
        }


async def handle_health_check_request() -> Dict[str, Any]:
    """
    Handle a health check HTTP request.
    
    Returns:
        Response dictionary with status_code and body
    """
    try:
        health_status = await get_health_status()
        
        status_code = 200 if health_status.get("status") == "healthy" else 503
        
        return {
            "status_code": status_code,
            "body": json.dumps(health_status),
            "headers": {"Content-Type": "application/json"}
        }
        
    except Exception as e:
        logger.error(f"Error in health check: {e}", exc_info=True)
        return {
            "status_code": 503,
            "body": json.dumps({"status": "unhealthy", "error": str(e)}),
            "headers": {"Content-Type": "application/json"}
        }


def parse_request(event: Dict[str, Any]) -> tuple[str, str, Dict[str, str]]:
    """
    Parse a serverless function event into method, path, body, and headers.
    
    This handles both Vercel and GCP Cloud Run/Functions event formats.
    """
    # Vercel format
    if "httpMethod" in event or "method" in event:
        method = event.get("httpMethod") or event.get("method", "GET")
        path = event.get("path") or event.get("rawPath", "/")
        body = event.get("body", "") or event.get("rawBody", "")
        headers = event.get("headers", {}) or event.get("multiValueHeaders", {})
        
        # Normalize headers (handle both single and multi-value)
        normalized_headers = {}
        for key, value in headers.items():
            if isinstance(value, list):
                normalized_headers[key.lower()] = value[0] if value else ""
            else:
                normalized_headers[key.lower()] = value
        
        return method, path, body, normalized_headers
    
    # GCP Cloud Run format (direct HTTP request)
    # This would be handled by FastAPI/Flask framework
    raise ValueError("Unsupported event format")


def create_response(status_code: int, body: Any, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Create a standardized response for serverless platforms.
    
    Args:
        status_code: HTTP status code
        body: Response body (will be JSON stringified if dict)
        headers: Optional headers dictionary
        
    Returns:
        Response dictionary
    """
    if isinstance(body, dict):
        body = json.dumps(body)
    
    response_headers = headers or {}
    if "Content-Type" not in response_headers:
        response_headers["Content-Type"] = "application/json"
    
    return {
        "statusCode": status_code,
        "body": body,
        "headers": response_headers
    }
