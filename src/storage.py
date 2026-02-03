"""
Persistent storage adapters for serverless nanobot deployment.

This module provides file-based storage using Google Cloud Storage
for persistent chat history, sessions, and agent actions.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import GCS (required for GCP deployment)
try:
    from google.cloud import storage as gcs_storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    logger.warning("google-cloud-storage not available. File persistence will be limited.")


class GCSFileStorage:
    """
    Google Cloud Storage adapter for persistent file storage.
    
    Stores chat history, sessions, and agent actions as JSON files in GCS.
    """
    
    def __init__(self, bucket_name: str, project_id: Optional[str] = None):
        """
        Initialize GCS file storage.
        
        Args:
            bucket_name: GCS bucket name
            project_id: GCP project ID (optional, uses default if not provided)
        """
        if not GCS_AVAILABLE:
            raise RuntimeError("google-cloud-storage package not installed")
        
        self.bucket_name = bucket_name
        self.client = gcs_storage.Client(project=project_id)
        self.bucket = self.client.bucket(bucket_name)
        
        # Ensure bucket exists
        if not self.bucket.exists():
            logger.info(f"Creating GCS bucket: {bucket_name}")
            self.bucket.create()
        
        logger.info(f"Initialized GCS file storage with bucket: {bucket_name}")
    
    def _get_session_path(self, session_key: str) -> str:
        """Get base path for a session in GCS."""
        # Sanitize session key for use in paths
        safe_key = session_key.replace(":", "_")
        return f"sessions/{safe_key}"
    
    def get_session(self, session_key: str) -> Optional[Dict[str, Any]]:
        """
        Get session data by session key.
        
        Args:
            session_key: Session key (e.g., "telegram:123456789")
            
        Returns:
            Session data dictionary or None if not found
        """
        try:
            session_path = f"{self._get_session_path(session_key)}/session.json"
            blob = self.bucket.blob(session_path)
            
            if not blob.exists():
                return None
            
            content = blob.download_as_text()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Error getting session {session_key}: {e}")
            return None
    
    def create_or_update_session(
        self,
        session_key: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create or update a session.
        
        Args:
            session_key: Session key (e.g., "telegram:123456789")
            user_id: User ID
            metadata: Optional session metadata
            
        Returns:
            Session document
        """
        try:
            # Get existing session or create new
            session = self.get_session(session_key)
            now = datetime.utcnow().isoformat()
            
            if session:
                session["updated_at"] = now
                session["user_id"] = user_id
                if metadata:
                    session["metadata"] = {**session.get("metadata", {}), **metadata}
            else:
                session = {
                    "session_key": session_key,
                    "user_id": user_id,
                    "created_at": now,
                    "updated_at": now,
                    "metadata": metadata or {}
                }
            
            # Save to GCS
            session_path = f"{self._get_session_path(session_key)}/session.json"
            blob = self.bucket.blob(session_path)
            blob.upload_from_string(
                json.dumps(session, indent=2),
                content_type="application/json"
            )
            
            logger.debug(f"Saved session {session_key} to GCS")
            return session
        except Exception as e:
            logger.error(f"Error creating/updating session {session_key}: {e}")
            raise
    
    def save_chat_message(
        self,
        session_key: str,
        message_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Save a chat message to history (appends to JSONL file).
        
        Args:
            session_key: Session key
            message_id: Unique message ID
            role: Message role ("user" or "assistant")
            content: Message content
            metadata: Optional message metadata
        """
        try:
            chat_history_path = f"{self._get_session_path(session_key)}/chat_history.jsonl"
            blob = self.bucket.blob(chat_history_path)
            
            message_doc = {
                "message_id": message_id,
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": metadata or {}
            }
            
            # Append to JSONL file
            message_line = json.dumps(message_doc) + "\n"
            
            if blob.exists():
                # Append to existing file
                existing_content = blob.download_as_text()
                new_content = existing_content + message_line
            else:
                # Create new file
                new_content = message_line
            
            blob.upload_from_string(new_content, content_type="application/x-ndjson")
            logger.debug(f"Saved chat message {message_id} for session {session_key}")
        except Exception as e:
            logger.error(f"Error saving chat message: {e}")
            # Don't raise - chat history is not critical for operation
    
    def get_chat_history(
        self,
        session_key: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get chat history for a session.
        
        Args:
            session_key: Session key
            limit: Maximum number of messages to return (None for all)
            
        Returns:
            List of message documents
        """
        try:
            chat_history_path = f"{self._get_session_path(session_key)}/chat_history.jsonl"
            blob = self.bucket.blob(chat_history_path)
            
            if not blob.exists():
                return []
            
            content = blob.download_as_text()
            messages = []
            
            # Parse JSONL file
            for line in content.strip().split("\n"):
                if line.strip():
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse chat history line: {e}")
                        continue
            
            # Return most recent messages first, optionally limited
            if limit:
                return messages[-limit:]
            return messages
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []
    
    def save_agent_action(
        self,
        session_key: str,
        action_type: str,
        action_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Save an agent action (appends to JSONL file).
        
        Args:
            session_key: Session key
            action_type: Type of action (e.g., "tool_call", "file_created", "search")
            action_data: Action data
            metadata: Optional metadata
            
        Returns:
            Action ID
        """
        try:
            import uuid
            action_id = str(uuid.uuid4())
            
            actions_path = f"{self._get_session_path(session_key)}/agent_actions.jsonl"
            blob = self.bucket.blob(actions_path)
            
            action_doc = {
                "action_id": action_id,
                "action_type": action_type,
                "action_data": action_data,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": metadata or {}
            }
            
            # Append to JSONL file
            action_line = json.dumps(action_doc) + "\n"
            
            if blob.exists():
                existing_content = blob.download_as_text()
                new_content = existing_content + action_line
            else:
                new_content = action_line
            
            blob.upload_from_string(new_content, content_type="application/x-ndjson")
            logger.debug(f"Saved agent action {action_id} for session {session_key}")
            return action_id
        except Exception as e:
            logger.error(f"Error saving agent action: {e}")
            # Don't raise - agent actions logging is not critical
            return ""
    
    def get_agent_actions(
        self,
        session_key: str,
        action_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get agent actions for a session.
        
        Args:
            session_key: Session key
            action_type: Optional filter by action type
            limit: Maximum number of actions to return (None for all)
            
        Returns:
            List of action documents
        """
        try:
            actions_path = f"{self._get_session_path(session_key)}/agent_actions.jsonl"
            blob = self.bucket.blob(actions_path)
            
            if not blob.exists():
                return []
            
            content = blob.download_as_text()
            actions = []
            
            # Parse JSONL file
            for line in content.strip().split("\n"):
                if line.strip():
                    try:
                        action = json.loads(line)
                        if action_type is None or action.get("action_type") == action_type:
                            actions.append(action)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse agent action line: {e}")
                        continue
            
            # Return most recent actions first, optionally limited
            if limit:
                return actions[-limit:]
            return actions
        except Exception as e:
            logger.error(f"Error getting agent actions: {e}")
            return []
    
    def upload_file(self, local_path: Path, remote_path: str) -> str:
        """
        Upload a file to GCS.
        
        Args:
            local_path: Local file path
            remote_path: Remote path in bucket (e.g., "sessions/telegram_123/file.txt")
            
        Returns:
            GCS URI (gs://bucket/path)
        """
        try:
            blob = self.bucket.blob(remote_path)
            blob.upload_from_filename(str(local_path))
            
            gcs_uri = f"gs://{self.bucket_name}/{remote_path}"
            logger.info(f"Uploaded file to GCS: {gcs_uri}")
            return gcs_uri
        except Exception as e:
            logger.error(f"Error uploading file to GCS: {e}")
            raise
    
    def download_file(self, remote_path: str, local_path: Path) -> bool:
        """
        Download a file from GCS.
        
        Args:
            remote_path: Remote path in bucket
            local_path: Local file path to save to
            
        Returns:
            True if successful, False otherwise
        """
        try:
            blob = self.bucket.blob(remote_path)
            if not blob.exists():
                logger.warning(f"File not found in GCS: {remote_path}")
                return False
            
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(local_path))
            logger.debug(f"Downloaded file from GCS: {remote_path} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"Error downloading file from GCS: {e}")
            return False
    
    def list_files(self, prefix: str = "") -> List[str]:
        """
        List files in bucket with given prefix.
        
        Args:
            prefix: Path prefix to filter by
            
        Returns:
            List of file paths
        """
        try:
            blobs = self.bucket.list_blobs(prefix=prefix)
            return [blob.name for blob in blobs]
        except Exception as e:
            logger.error(f"Error listing files in GCS: {e}")
            return []
    
    def delete_file(self, remote_path: str) -> bool:
        """
        Delete a file from GCS.
        
        Args:
            remote_path: Remote path in bucket
            
        Returns:
            True if successful, False otherwise
        """
        try:
            blob = self.bucket.blob(remote_path)
            if blob.exists():
                blob.delete()
                logger.info(f"Deleted file from GCS: {remote_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting file from GCS: {e}")
            return False
    
    def sync_workspace_to_gcs(self, workspace_path: Path, session_key: str):
        """
        Sync entire workspace directory to GCS for a session.
        
        Args:
            workspace_path: Local workspace directory
            session_key: Session key (used as prefix)
        """
        try:
            if not workspace_path.exists():
                return
            
            prefix = f"{self._get_session_path(session_key)}/files/"
            
            # Walk through workspace and upload all files
            for file_path in workspace_path.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(workspace_path)
                    remote_path = f"{prefix}{relative_path}"
                    self.upload_file(file_path, remote_path)
            
            logger.info(f"Synced workspace to GCS for session {session_key}")
        except Exception as e:
            logger.error(f"Error syncing workspace to GCS: {e}")
    
    def sync_gcs_to_workspace(self, workspace_path: Path, session_key: str):
        """
        Sync files from GCS to local workspace for a session.
        
        Args:
            workspace_path: Local workspace directory
            session_key: Session key (used as prefix)
        """
        try:
            prefix = f"{self._get_session_path(session_key)}/files/"
            files = self.list_files(prefix=prefix)
            
            for remote_path in files:
                # Get relative path from prefix
                relative_path = remote_path[len(prefix):]
                local_path = workspace_path / relative_path
                
                self.download_file(remote_path, local_path)
            
            logger.info(f"Synced GCS to workspace for session {session_key}")
        except Exception as e:
            logger.error(f"Error syncing GCS to workspace: {e}")


class PersistentStorageManager:
    """
    Manager that coordinates GCS file storage for all persistent data.
    
    Stores everything in GCS:
    - Sessions as JSON files
    - Chat history as JSONL files
    - Agent actions as JSONL files
    - Workspace files in session directories
    """
    
    def __init__(
        self,
        gcs_bucket_name: str,
        gcp_project_id: Optional[str] = None
    ):
        """
        Initialize persistent storage manager.
        
        Args:
            gcs_bucket_name: GCS bucket name (required)
            gcp_project_id: GCP project ID (optional)
        """
        if not gcs_bucket_name:
            raise ValueError("GCS_BUCKET_NAME is required for persistent storage")
        
        self.gcs_storage = GCSFileStorage(gcs_bucket_name, gcp_project_id)
        logger.info("Initialized persistent storage manager with GCS")
    
    def get_session(self, session_key: str) -> Optional[Dict[str, Any]]:
        """Get session data."""
        return self.gcs_storage.get_session(session_key)
    
    def create_or_update_session(
        self,
        session_key: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create or update session."""
        return self.gcs_storage.create_or_update_session(session_key, user_id, metadata)
    
    def save_chat_message(
        self,
        session_key: str,
        message_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Save chat message."""
        self.gcs_storage.save_chat_message(session_key, message_id, role, content, metadata)
    
    def get_chat_history(
        self,
        session_key: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get chat history."""
        return self.gcs_storage.get_chat_history(session_key, limit)
    
    def save_agent_action(
        self,
        session_key: str,
        action_type: str,
        action_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Save agent action."""
        return self.gcs_storage.save_agent_action(session_key, action_type, action_data, metadata)
    
    def get_agent_actions(
        self,
        session_key: str,
        action_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get agent actions."""
        return self.gcs_storage.get_agent_actions(session_key, action_type, limit)
    
    def sync_files_to_storage(self, workspace_path: Path, session_key: str):
        """Sync files to persistent storage."""
        self.gcs_storage.sync_workspace_to_gcs(workspace_path, session_key)
    
    def sync_files_from_storage(self, workspace_path: Path, session_key: str):
        """Sync files from persistent storage."""
        self.gcs_storage.sync_gcs_to_workspace(workspace_path, session_key)
    
    def close(self):
        """Close storage connections (no-op for GCS)."""
        pass
