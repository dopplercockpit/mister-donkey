"""
Session Logger - Tracks session metrics and logs to JSON file
"""
import json
import os
from datetime import datetime
from typing import Optional
from threading import Lock

class SessionLogger:
    def __init__(self, log_file: str = "sessions_log.json"):
        self.log_file = log_file
        self.lock = Lock()
        self._ensure_log_file_exists()

    def _ensure_log_file_exists(self):
        """Create log file if it doesn't exist"""
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w') as f:
                json.dump({"sessions": []}, f, indent=2)

    def _read_log(self) -> dict:
        """Read the current log file"""
        with open(self.log_file, 'r') as f:
            return json.load(f)

    def _write_log(self, data: dict):
        """Write to the log file"""
        with open(self.log_file, 'w') as f:
            json.dump(data, f, indent=2)

    def generate_session_id(self) -> str:
        """
        Generate session ID in format: DDMMYYXX
        Where XX is the count of sessions for that day
        """
        with self.lock:
            now = datetime.now()
            date_prefix = now.strftime("%d%m%y")

            log_data = self._read_log()

            # Count sessions for today
            today_sessions = [
                s for s in log_data["sessions"]
                if s["session_id"].startswith(date_prefix)
            ]

            session_count = len(today_sessions) + 1
            session_id = f"{date_prefix}{session_count:02d}"

            return session_id

    def create_session(self, session_id: str) -> dict:
        """Create a new session entry in the log"""
        with self.lock:
            log_data = self._read_log()

            session_entry = {
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "prompts_count": 0,
                "responses_count": 0,
                "errors": []
            }

            log_data["sessions"].append(session_entry)
            self._write_log(log_data)

            print(f"📝 Session logged: {session_id}")
            return session_entry

    def update_session(self, session_id: str, prompts: Optional[int] = None,
                      responses: Optional[int] = None, error: Optional[str] = None):
        """Update session metrics"""
        with self.lock:
            log_data = self._read_log()

            # Find the session
            session = None
            for s in log_data["sessions"]:
                if s["session_id"] == session_id:
                    session = s
                    break

            if not session:
                print(f"⚠️ Session {session_id} not found in log")
                return

            # Update metrics
            if prompts is not None:
                session["prompts_count"] = prompts
            if responses is not None:
                session["responses_count"] = responses
            if error:
                session["errors"].append({
                    "timestamp": datetime.now().isoformat(),
                    "error": error
                })

            session["last_updated"] = datetime.now().isoformat()
            self._write_log(log_data)

    def increment_prompts(self, session_id: str):
        """Increment prompt count for a session"""
        with self.lock:
            log_data = self._read_log()

            for session in log_data["sessions"]:
                if session["session_id"] == session_id:
                    session["prompts_count"] = session.get("prompts_count", 0) + 1
                    session["last_updated"] = datetime.now().isoformat()
                    self._write_log(log_data)
                    return

    def increment_responses(self, session_id: str):
        """Increment response count for a session"""
        with self.lock:
            log_data = self._read_log()

            for session in log_data["sessions"]:
                if session["session_id"] == session_id:
                    session["responses_count"] = session.get("responses_count", 0) + 1
                    session["last_updated"] = datetime.now().isoformat()
                    self._write_log(log_data)
                    return

    def log_error(self, session_id: str, error: str):
        """Log an error for a session"""
        with self.lock:
            log_data = self._read_log()

            for session in log_data["sessions"]:
                if session["session_id"] == session_id:
                    if "errors" not in session:
                        session["errors"] = []
                    session["errors"].append({
                        "timestamp": datetime.now().isoformat(),
                        "error": error
                    })
                    session["last_updated"] = datetime.now().isoformat()
                    self._write_log(log_data)
                    return

    def get_session_stats(self, session_id: str) -> Optional[dict]:
        """Get statistics for a specific session"""
        log_data = self._read_log()

        for session in log_data["sessions"]:
            if session["session_id"] == session_id:
                return session

        return None

# Global instance
session_logger = SessionLogger()
