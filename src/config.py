"""Configuration loader that converts environment variables to nanobot config format."""

import os
import json
from typing import Dict, Any, Optional


def load_config_from_env() -> Dict[str, Any]:
    """
    Load nanobot configuration from environment variables.
    
    Returns a configuration dictionary compatible with nanobot's expected format.
    """
    config: Dict[str, Any] = {
        "agents": {
            "defaults": {
                "model": os.getenv("NANOBOT_MODEL", "anthropic/claude-opus-4-5")
            }
        },
        "providers": {},
        "channels": {
            "telegram": {
                "enabled": False
            },
            "whatsapp": {
                "enabled": False
            }
        },
        "tools": {}
    }
    
    # Load OpenRouter provider configuration
    openrouter_api_key = os.getenv("NANOBOT_OPENROUTER_API_KEY")
    if openrouter_api_key:
        config["providers"]["openrouter"] = {
            "apiKey": openrouter_api_key
        }
        # Optional custom API base URL
        api_base = os.getenv("NANOBOT_OPENROUTER_API_BASE")
        if api_base:
            config["providers"]["openrouter"]["apiBase"] = api_base
    
    # Load Telegram channel configuration
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_allowed_users = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    
    if telegram_token:
        config["channels"]["telegram"] = {
            "enabled": True,
            "token": telegram_token,
            "allowFrom": [uid.strip() for uid in telegram_allowed_users.split(",") if uid.strip()]
        }
    
    # WhatsApp is not supported in serverless (requires QR scanning)
    # But we keep the structure for compatibility
    config["channels"]["whatsapp"]["enabled"] = False
    
    # Load web search tool configuration
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if brave_api_key:
        config["tools"]["web"] = {
            "search": {
                "apiKey": brave_api_key
            }
        }
    
    return config


def get_mongodb_uri() -> Optional[str]:
    """Get MongoDB connection URI from environment variables (deprecated - using GCS only)."""
    return os.getenv("MONGODB_URI")


def validate_config(config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate that required configuration is present.
    
    Returns:
        (is_valid, error_message)
    """
    # Check for LLM provider
    if not config.get("providers"):
        return False, "No LLM provider configured. Set NANOBOT_OPENROUTER_API_KEY"
    
    # Check for at least one enabled channel
    channels = config.get("channels", {})
    telegram_enabled = channels.get("telegram", {}).get("enabled", False)
    whatsapp_enabled = channels.get("whatsapp", {}).get("enabled", False)
    
    if not telegram_enabled and not whatsapp_enabled:
        return False, "No channels enabled. Configure TELEGRAM_BOT_TOKEN for Telegram support"
    
    # Check Telegram-specific requirements
    if telegram_enabled:
        telegram_config = channels.get("telegram", {})
        if not telegram_config.get("token"):
            return False, "TELEGRAM_BOT_TOKEN is required when Telegram is enabled"
        if not telegram_config.get("allowFrom"):
            return False, "TELEGRAM_ALLOWED_USERS is required when Telegram is enabled"
    
    # GCS bucket is now required instead of MongoDB
    gcs_bucket_name = os.getenv("GCS_BUCKET_NAME")
    if not gcs_bucket_name:
        return False, "GCS_BUCKET_NAME is required for persistent storage"
    
    return True, None


def create_nanobot_config_file(config: Dict[str, Any], config_path: str = "/tmp/.nanobot/config.json") -> str:
    """
    Create a nanobot config file from the configuration dictionary.
    
    This is used to initialize nanobot with the serverless configuration.
    """
    import os
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    return config_path
