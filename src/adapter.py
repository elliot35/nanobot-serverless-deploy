"""Gateway adapter that wraps nanobot for serverless execution."""

import os
import sys
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from functools import lru_cache
import httpx
import uuid
import shutil
from datetime import datetime

from .config import load_config_from_env, validate_config, create_nanobot_config_file
from .storage import PersistentStorageManager

logger = logging.getLogger(__name__)

# Try to import nanobot at module level to catch import errors early
try:
    import nanobot
    logger.debug(f"nanobot module found at: {getattr(nanobot, '__file__', 'unknown')}")
except ImportError as e:
    logger.warning(f"nanobot import failed at module level: {e}. Will retry at runtime.")
    # Don't fail here - let get_gateway_instance handle it with better error messages

# Global gateway instance (reused across requests)
_gateway_instance: Optional[Any] = None
_gateway_lock = asyncio.Lock()


def get_gateway_instance():
    """
    Get or create the nanobot gateway instance.
    
    This uses lazy initialization and reuses the instance across requests
    to optimize cold starts in serverless environments.
    """
    global _gateway_instance
    
    if _gateway_instance is not None:
        return _gateway_instance
    
    try:
        # Import nanobot components with correct names
        from nanobot.bus.queue import MessageBus
        from nanobot.bus.events import InboundMessage, OutboundMessage
        from nanobot.agent.loop import AgentLoop
        from nanobot.session.manager import SessionManager
        from nanobot.config.loader import load_config
        from nanobot.providers.litellm_provider import LiteLLMProvider
        
        # Load configuration from environment
        config_dict = load_config_from_env()
        is_valid, error_msg = validate_config(config_dict)
        
        if not is_valid:
            raise ValueError(f"Invalid configuration: {error_msg}")
        
        # Create config file for nanobot
        config_path_str = create_nanobot_config_file(config_dict)
        config_path = Path(config_path_str)
        
        # Set environment variable so nanobot can find the config
        os.environ["NANOBOT_CONFIG_PATH"] = str(config_path)
        
        # Load nanobot config (expects Path object)
        config = load_config(config_path)
        
        # Create workspace directory (serverless-friendly location)
        workspace = Path("/tmp/nanobot_workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        
        # Initialize persistent storage (GCS only)
        gcs_bucket_name = os.getenv("GCS_BUCKET_NAME")
        if not gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME is required for persistent storage")
        
        gcp_project_id = os.getenv("GCP_PROJECT_ID")
        
        storage_manager = PersistentStorageManager(
            gcs_bucket_name=gcs_bucket_name,
            gcp_project_id=gcp_project_id
        )
        
        # Initialize message bus
        bus = MessageBus()
        
        # Initialize LLM provider
        provider_config = config.providers.openrouter
        if not provider_config.api_key:
            raise ValueError("No LLM provider configured. Set NANOBOT_OPENROUTER_API_KEY")
        
        provider = LiteLLMProvider(
            api_key=provider_config.api_key,
            api_base=provider_config.api_base
        )
        
        # Get model from config
        model = config.agents.defaults.model
        if not model:
            model = os.getenv("NANOBOT_MODEL", "anthropic/claude-opus-4-5")
        
        # Get brave API key for web search
        brave_api_key = config.tools.web.search.api_key if config.tools.web.search.api_key else None
        
        # Initialize agent loop
        agent_loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace,
            model=model,
            brave_api_key=brave_api_key
        )
        
        # Initialize session manager (uses workspace for temporary session state)
        # Note: nanobot's SessionManager uses file-based storage by default
        # Persistent storage is handled by our GCS-based PersistentStorageManager
        session_manager = SessionManager(workspace=workspace)
        
        # Create gateway-like wrapper
        gateway = ServerlessGateway(
            bus=bus,
            agent_loop=agent_loop,
            session_manager=session_manager,
            config=config,
            workspace=workspace,
            storage_manager=storage_manager
        )
        
        _gateway_instance = gateway
        logger.info("nanobot gateway initialized successfully")
        
        return gateway
        
    except ImportError as e:
        logger.error(f"Failed to import nanobot: {e}", exc_info=True)
        # Include the actual error message for debugging
        error_msg = f"nanobot-ai package not found or import failed. Error: {str(e)}. Install it with: pip install nanobot-ai"
        raise RuntimeError(error_msg) from e
    except Exception as e:
        logger.error(f"Failed to initialize gateway: {e}", exc_info=True)
        raise


class ServerlessGateway:
    """
    Serverless-compatible gateway wrapper for nanobot.
    
    This adapter bridges nanobot's long-running gateway model with
    serverless request/response model.
    """
    
    def __init__(self, bus, agent_loop, session_manager, config, workspace, storage_manager):
        self.bus = bus
        self.agent_loop = agent_loop
        self.session_manager = session_manager
        self.config = config
        self.workspace = workspace
        self.storage_manager = storage_manager
    
    async def handle_telegram_webhook(self, update: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a Telegram webhook update.
        
        Args:
            update: Telegram update object from webhook
            
        Returns:
            Response dictionary
        """
        try:
            # Extract message from update
            message = update.get("message") or update.get("edited_message")
            if not message:
                logger.warning("No message found in Telegram update")
                return {"ok": True, "handled": False}
            
            # Get chat and user info
            chat = message.get("chat", {})
            user = message.get("from", {})
            text = message.get("text", "")
            
            chat_id = str(chat.get("id"))
            user_id = str(user.get("id"))
            
            logger.info(f"Received message from user {user_id} in chat {chat_id}: {text[:50]}")
            
            # Check if user is allowed
            telegram_config = self.config.channels.telegram
            allowed_users = telegram_config.allow_from
            
            if allowed_users and user_id not in allowed_users:
                logger.warning(f"User {user_id} not in allowed list")
                return {"ok": True, "handled": False, "error": "User not allowed"}
            
            # Create session key
            session_key = f"telegram:{chat_id}"
            
            # Load session from persistent storage
            session = self.storage_manager.get_session(session_key)
            if not session:
                # Create new session
                self.storage_manager.create_or_update_session(
                    session_key=session_key,
                    user_id=user_id,
                    metadata={"chat_type": chat.get("type", "unknown")}
                )
            
            # Sync files from storage before processing
            session_workspace = self.workspace / session_key.replace(":", "_")
            session_workspace.mkdir(parents=True, exist_ok=True)
            self.storage_manager.sync_files_from_storage(session_workspace, session_key)
            
            # Load previous chat history to provide context
            chat_history = self.storage_manager.get_chat_history(session_key, limit=50)
            logger.debug(f"Loaded {len(chat_history)} previous messages for session {session_key}")
            
            # Copy synced files to agent workspace so agent can access them
            if session_workspace.exists():
                for session_file in session_workspace.rglob("*"):
                    if session_file.is_file():
                        relative_path = session_file.relative_to(session_workspace)
                        agent_file = self.agent_loop.workspace / relative_path
                        agent_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(session_file, agent_file)
            
            # Save user message to chat history
            message_id = str(uuid.uuid4())
            self.storage_manager.save_chat_message(
                session_key=session_key,
                message_id=message_id,
                role="user",
                content=text,
                metadata={"telegram_message_id": message.get("message_id")}
            )
            
            # Build context from chat history if available
            # Note: nanobot's process_direct may handle session context internally,
            # but we ensure files are available and log history for debugging
            if chat_history:
                logger.info(f"Processing message with {len(chat_history)} previous messages in context")
            
            # Process message directly using agent loop's process_direct method
            # The agent will have access to:
            # 1. Files synced from GCS (in workspace)
            # 2. Session key (for internal session management)
            # 3. Chat history is stored but agent may use its own session management
            response_text = await self.agent_loop.process_direct(
                content=text,
                session_key=session_key
            )
            
            # Save assistant response to chat history
            if response_text:
                response_message_id = str(uuid.uuid4())
                self.storage_manager.save_chat_message(
                    session_key=session_key,
                    message_id=response_message_id,
                    role="assistant",
                    content=response_text
                )
            
            # Sync files from agent workspace to session workspace, then to storage
            # AgentLoop creates files in its workspace, we need to copy them
            agent_workspace_files = list(self.agent_loop.workspace.rglob("*"))
            for agent_file in agent_workspace_files:
                if agent_file.is_file():
                    # Copy to session workspace
                    relative_path = agent_file.relative_to(self.agent_loop.workspace)
                    session_file = session_workspace / relative_path
                    session_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(agent_file, session_file)
            
            # Sync files back to storage after processing
            self.storage_manager.sync_files_to_storage(session_workspace, session_key)
            
            # Log agent actions (if any files were created/modified)
            if session_workspace.exists():
                files_created = [f for f in session_workspace.rglob("*") if f.is_file()]
                if files_created:
                    self.storage_manager.save_agent_action(
                        session_key=session_key,
                        action_type="file_operation",
                        action_data={
                            "files_count": len(files_created),
                            "workspace": str(session_workspace)
                        }
                    )
            
            # Check if we have a response to send
            if not response_text or not response_text.strip():
                logger.warning(f"No response generated for chat {chat_id}")
                response_text = "I received your message but couldn't generate a response."
            
            # Send response back via Telegram API
            telegram_token = telegram_config.token
            if not telegram_token:
                logger.error("Telegram bot token not found in config")
                return {
                    "ok": False,
                    "error": "Telegram bot token not configured"
                }
            
            # Send message to Telegram
            telegram_api_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        telegram_api_url,
                        json={
                            "chat_id": chat_id,
                            "text": response_text
                        }
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    if result.get("ok"):
                        logger.info(f"Successfully sent response to chat {chat_id}")
                    else:
                        logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
                        
            except httpx.TimeoutException:
                logger.error("Timeout sending message to Telegram API")
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error sending message to Telegram: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                logger.error(f"Error sending message to Telegram: {e}", exc_info=True)
            
            return {
                "ok": True,
                "handled": True,
                "response": response_text
            }
            
        except Exception as e:
            logger.error(f"Error handling Telegram webhook: {e}", exc_info=True)
            return {
                "ok": False,
                "error": str(e)
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform a health check of the gateway."""
        try:
            # Check if components are initialized
            checks = {
                "bus": self.bus is not None,
                "agent_loop": self.agent_loop is not None,
                "session_manager": self.session_manager is not None,
                "config": self.config is not None,
                "workspace": self.workspace.exists() if self.workspace else False,
                "storage_manager": self.storage_manager is not None,
                "gcs": self.storage_manager.gcs_storage is not None if self.storage_manager else False
            }
            
            all_healthy = all(checks.values())
            
            return {
                "status": "healthy" if all_healthy else "degraded",
                "checks": checks
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            return {
                "status": "unhealthy",
                "error": str(e)
            }


async def handle_telegram_update(update: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to handle a Telegram update.
    
    This function handles the async initialization and processing.
    """
    gateway = get_gateway_instance()
    return await gateway.handle_telegram_webhook(update)


async def get_health_status() -> Dict[str, Any]:
    """Get health status of the gateway."""
    try:
        gateway = get_gateway_instance()
        return await gateway.health_check()
    except Exception as e:
        logger.error(f"Health check error: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "error": str(e)
        }
