# conversation_manager.py (NEW FILE)
# Fixes Issue #3: Adds conversation continuity

import json
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import os

class ConversationManager:
    """
    Manages conversation history for weather chat sessions.
    Supports session management, history storage, and cleanup.
    """
    
    def __init__(self, storage_dir="/home/claude/conversation_sessions", max_age_minutes=60):
        self.storage_dir = storage_dir
        self.max_age_minutes = max_age_minutes
        self.sessions: Dict[str, Dict] = {}
        
        # Create storage directory if it doesn't exist
        os.makedirs(storage_dir, exist_ok=True)
        
        # Load existing sessions from disk
        self._load_sessions()
    
    def _load_sessions(self):
        """Load sessions from disk on startup"""
        try:
            session_files = [f for f in os.listdir(self.storage_dir) if f.endswith('.json')]
            for file in session_files:
                session_id = file.replace('.json', '')
                with open(os.path.join(self.storage_dir, file), 'r') as f:
                    self.sessions[session_id] = json.load(f)
            print(f"✅ Loaded {len(self.sessions)} conversation sessions")
        except Exception as e:
            print(f"⚠️ Failed to load sessions: {e}")
    
    def _save_session(self, session_id: str):
        """Save a session to disk"""
        try:
            filepath = os.path.join(self.storage_dir, f"{session_id}.json")
            with open(filepath, 'w') as f:
                json.dump(self.sessions[session_id], f)
        except Exception as e:
            print(f"⚠️ Failed to save session {session_id}: {e}")
    
    def create_session(self, user_id: Optional[str] = None) -> str:
        """Create a new conversation session"""
        # Generate unique session ID
        session_id = f"session_{int(time.time() * 1000)}"
        if user_id:
            session_id = f"{user_id}_{session_id}"
        
        self.sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "messages": [],
            "metadata": {
                "location": None,
                "tone": "sarcastic",
                "message_count": 0
            }
        }
        
        self._save_session(session_id)
        print(f"🆕 Created new session: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Retrieve a session by ID"""
        session = self.sessions.get(session_id)
        
        if session:
            # Check if session has expired
            last_activity = datetime.fromisoformat(session["last_activity"])
            if datetime.now() - last_activity > timedelta(minutes=self.max_age_minutes):
                print(f"⏰ Session {session_id} expired")
                self.delete_session(session_id)
                return None
        
        return session
    
    def add_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a message to the conversation history"""
        session = self.get_session(session_id)
        
        if not session:
            print(f"❌ Session {session_id} not found")
            return False
        
        message = {
            "role": role,  # 'user' or 'assistant'
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        session["messages"].append(message)
        session["last_activity"] = datetime.now().isoformat()
        session["metadata"]["message_count"] = len(session["messages"])
        
        self._save_session(session_id)
        return True
    
    def get_conversation_history(self, session_id: str, format_for_openai: bool = True) -> List[Dict]:
        """
        Get conversation history for a session.
        
        Args:
            session_id: Session identifier
            format_for_openai: If True, returns format compatible with OpenAI API
                              [{role: str, content: str}, ...]
        """
        session = self.get_session(session_id)
        
        if not session:
            return []
        
        if format_for_openai:
            # Return only role and content for OpenAI API
            return [
                {"role": msg["role"], "content": msg["content"]}
                for msg in session["messages"]
            ]
        
        # Return full message objects with timestamps and metadata
        return session["messages"]
    
    def update_session_metadata(self, session_id: str, key: str, value):
        """Update session metadata (location, tone, etc.)"""
        session = self.get_session(session_id)
        
        if session:
            session["metadata"][key] = value
            self._save_session(session_id)
            return True
        
        return False
    
    def delete_session(self, session_id: str):
        """Delete a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            
            # Remove from disk
            filepath = os.path.join(self.storage_dir, f"{session_id}.json")
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                print(f"🗑️ Deleted session: {session_id}")
            except Exception as e:
                print(f"⚠️ Failed to delete session file: {e}")
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions (called periodically)"""
        now = datetime.now()
        expired = []
        
        for session_id, session in self.sessions.items():
            last_activity = datetime.fromisoformat(session["last_activity"])
            if now - last_activity > timedelta(minutes=self.max_age_minutes):
                expired.append(session_id)
        
        for session_id in expired:
            self.delete_session(session_id)
        
        if expired:
            print(f"🧹 Cleaned up {len(expired)} expired sessions")
        
        return len(expired)
    
    def get_session_count(self) -> int:
        """Get total number of active sessions"""
        return len(self.sessions)
    
    def get_session_summary(self, session_id: str) -> Optional[Dict]:
        """Get a summary of the session (for debugging/analytics)"""
        session = self.get_session(session_id)
        
        if not session:
            return None
        
        return {
            "session_id": session_id,
            "user_id": session.get("user_id"),
            "created_at": session["created_at"],
            "last_activity": session["last_activity"],
            "message_count": session["metadata"]["message_count"],
            "location": session["metadata"].get("location"),
            "tone": session["metadata"].get("tone"),
            "age_minutes": (datetime.now() - datetime.fromisoformat(session["created_at"])).total_seconds() / 60
        }


# Global singleton instance
conversation_manager = ConversationManager()


# Helper functions for easy access
def create_conversation():
    """Create a new conversation session"""
    return conversation_manager.create_session()


def get_conversation(session_id: str):
    """Get conversation history"""
    return conversation_manager.get_conversation_history(session_id, format_for_openai=True)


def add_message_to_conversation(session_id: str, role: str, content: str, metadata: dict = None):
    """Add a message to conversation"""
    return conversation_manager.add_message(session_id, role, content, metadata)


def update_conversation_metadata(session_id: str, key: str, value):
    """Update conversation metadata"""
    return conversation_manager.update_session_metadata(session_id, key, value)