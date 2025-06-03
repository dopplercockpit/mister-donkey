# weather_agent.py
# Proactive weather‐monitoring “agent” for Mister Donkey

import time
import threading
from datetime import datetime, timedelta
from dopplertower_engine import get_openweather_current, get_openweather_forecast, get_weather_alerts
from geo_utils_helper import reverse_geolocate
from push_helper import send_push_firebase as send_push_notification, send_email_alert
import json
import os
from flask import Blueprint, request, jsonify
import sqlite3
from typing import Dict, List, Optional, Any

# Create Flask blueprint for weather-agent endpoints
weather_agent_bp = Blueprint("weather_agent", __name__)

class WeatherAgent:
    def __init__(self):
        # In‐memory map of active sessions (user_id → session_data)
        self.active_sessions: Dict[str, Dict] = {}  
        
        # Thresholds for simple “non‐GPT” alerts
        self.alert_thresholds = {
            "temp_change": 5,           # degrees Celsius
            "precipitation_start": 0.5, # mm/hour
            "wind_speed": 10,           # m/s
            "visibility": 1000,         # meters
        }

        self.running = False
        self.check_interval = 300  # check every 5 minutes

        # Where we store sessions + history
        self.db_path = "weather_agent.db"

        # DISABLE GPT‐analysis for now (stub “call_gpt_weather_analysis” isn’t defined in your engine)
        self.gpt_analysis_enabled = False

        # Create or migrate DB tables
        self._init_database()

    def _init_database(self):
        """Initialize SQLite DB for persistent sessions + history."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    user_id TEXT PRIMARY KEY,
                    email TEXT,
                    lat REAL,
                    lon REAL,
                    location_name TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    baseline_weather TEXT,
                    last_alert_time TEXT,
                    notification_preferences TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    alert_type TEXT,
                    message TEXT,
                    severity TEXT,
                    sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES user_sessions (user_id)
                )
            """)

    def register_user_session(
        self,
        user_id: str,
        lat: float,
        lon: float,
        duration_hours: int = 6,
        email: Optional[str] = None,
        notification_prefs: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Start proactive monitoring for this user_id at given lat/lon for duration_hours.
        Returns a status dict with “registered” or “error.”
        """
        try:
            # Reverse‐geocode to human‐readable location
            location_name = reverse_geolocate(lat, lon) or f"{lat:.2f}, {lon:.2f}"

            # Grab baseline weather so we can detect changes “since monitoring started”
            current_weather = get_openweather_current(lat, lon)

            # Default notification preferences
            if notification_prefs is None:
                notification_prefs = {
                    "email": bool(email),
                    "push": True,
                    "log_file": True,
                    "severity_threshold": "medium",  # low / medium / high
                }

            sess = {
                "lat": lat,
                "lon": lon,
                "location_name": location_name,
                "email": email,
                "start_time": datetime.now(),
                "end_time": datetime.now() + timedelta(hours=duration_hours),
                "last_check": datetime.now(),
                "baseline_weather": current_weather,
                "last_alert_time": None,
                "alert_cooldown": 30,  # minutes between the same alert
                "notification_prefs": notification_prefs,
                "alert_count": 0,
            }

            # Save in memory
            self.active_sessions[user_id] = sess

            # Persist to DB
            self._save_session_to_db(user_id, sess)

            print(f"🤖 Registered user {user_id} for monitoring at {location_name}")
            return {
                "status": "registered",
                "location": location_name,
                "monitoring_until": sess["end_time"].isoformat(),
                "notification_preferences": notification_prefs
            }

        except Exception as e:
            print(f"❌ Failed to register user {user_id}: {e}")
            return {"status": "error", "message": str(e)}

    def _save_session_to_db(self, user_id: str, session_data: Dict):
        """Persist or update a user_session row in the DB."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_sessions
                (user_id, email, lat, lon, location_name, start_time, end_time, baseline_weather, notification_preferences)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                session_data.get("email"),
                session_data["lat"],
                session_data["lon"],
                session_data["location_name"],
                session_data["start_time"].isoformat(),
                session_data["end_time"].isoformat(),
                json.dumps(session_data["baseline_weather"]),
                json.dumps(session_data["notification_prefs"])
            ))

    def _load_sessions_from_db(self):
        """On startup, load any non‐expired sessions from DB back into memory."""
        now_iso = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT user_id, email, lat, lon, location_name, start_time, end_time, baseline_weather, last_alert_time, notification_preferences
                FROM user_sessions
                WHERE end_time > ?
            """, (now_iso,))

            for row in cursor.fetchall():
                user_id = row[0]
                session_data = {
                    "lat": row[2],
                    "lon": row[3],
                    "location_name": row[4],
                    "email": row[1],
                    "start_time": datetime.fromisoformat(row[5]),
                    "end_time": datetime.fromisoformat(row[6]),
                    "baseline_weather": json.loads(row[7]) if row[7] else None,
                    "last_alert_time": datetime.fromisoformat(row[8]) if row[8] else None,
                    "alert_cooldown": 30,
                    "notification_prefs": json.loads(row[9]) if row[9] else {},
                    "alert_count": 0,
                    "last_check": datetime.now(),
                }
                self.active_sessions[user_id] = session_data
                print(f"🔄 Restored session for {user_id} at {session_data['location_name']}")

    def check_weather_changes(self, user_id: str, session_data: Dict) -> List[Dict]:
        """
        Check if weather has changed significantly since baseline or next‐3hr forecast.
        Returns a list of “warning” dicts (possibly empty).
        """
        try:
            lat, lon = session_data["lat"], session_data["lon"]
            current_weather = get_openweather_current(lat, lon)
            forecast = get_openweather_forecast(lat, lon)
            alerts_data = get_weather_alerts(lat, lon)

            warnings: List[Dict] = []

            # 1) Threshold‐based alerts (e.g. temp difference ≥ threshold)
            thresh_warnings = self._check_threshold_alerts(session_data, current_weather, forecast)
            warnings.extend(thresh_warnings)

            # 2) GPT‐based analysis (DISABLED by default)
            if self.gpt_analysis_enabled:
                gpt_warnings = self._check_gpt_analysis(session_data, current_weather, forecast)
                warnings.extend(gpt_warnings)

            # 3) “Official” severe alerts from the API
            if alerts_data:
                for alert in alerts_data:
                    warnings.append({
                        "type": "severe_alert",
                        "message": f"🚨 {alert.get('event','Weather Alert')}: {alert.get('desc','')[:100]}...",
                        "severity": "high",
                        "source": "official_alert"
                    })

            return warnings

        except Exception as e:
            print(f"❌ Error checking weather for {user_id}: {e}")
            return []

    def _check_threshold_alerts(self, session_data: Dict, current: Dict, forecast: Dict) -> List[Dict]:
        """
        Compare “baseline” vs. current to see if temp changed by ≥ threshold.
        Also check next‐3hr forecast for temp, precipitation, wind changes.
        """
        warnings: List[Dict] = []
        baseline = session_data.get("baseline_weather")
        if baseline and baseline.get("main") and current.get("main"):
            b_temp = baseline["main"].get("temp")
            c_temp = current["main"].get("temp")
            if b_temp is not None and c_temp is not None:
                diff = abs(c_temp - b_temp)
                if diff >= self.alert_thresholds["temp_change"]:
                    warnings.append({
                        "type": "temperature_change",
                        "message": f"🌡️ Temperature changed by {diff:.1f}°C since start ({b_temp:.1f}°C ➡ {c_temp:.1f}°C)",
                        "severity": "medium",
                        "source": "threshold"
                    })

        # Next 3hr forecast checks
        if forecast and forecast.get("list"):
            upcoming = self._check_upcoming_changes(current, forecast)
            warnings.extend(upcoming)

        return warnings

    def _check_gpt_analysis(self, session_data: Dict, current: Dict, forecast: Dict) -> List[Dict]:
        """
        Stub GPT‐analysis (disabled). If you later implement `call_gpt_weather_analysis`, re‐enable.
        """
        # This block never runs, because self.gpt_analysis_enabled=False
        return []

    def _check_upcoming_changes(self, current: Dict, forecast: Dict) -> List[Dict]:
        """
        Inspect the next 3 forecast entries for temp jumps, rain start, high wind, severe conditions.
        """
        warnings: List[Dict] = []
        now = datetime.now()

        try:
            c_temp = current.get("main", {}).get("temp")
            c_cond = current.get("weather", [{}])[0].get("main", "")

            for item in forecast.get("list", [])[:3]:
                f_time = datetime.fromtimestamp(item["dt"])
                if f_time <= now:
                    continue

                f_main = item.get("main", {})
                f_temp = f_main.get("temp")
                f_cond = item.get("weather", [{}])[0].get("main", "")
                f_rain = item.get("rain", {}).get("1h", 0) or 0
                f_wind = item.get("wind", {}).get("speed", 0) or 0
                f_label = f_time.strftime("%H:%M")

                # Temp changes
                if c_temp is not None and f_temp is not None:
                    delta = f_temp - c_temp
                    if abs(delta) >= self.alert_thresholds["temp_change"]:
                        direction = "drop" if delta < 0 else "rise"
                        warnings.append({
                            "type": "upcoming_temp_change",
                            "message": f"🌡️ Temperature will {direction} by {abs(delta):.1f}°C by {f_label} ({c_temp:.1f}°C ➡ {f_temp:.1f}°C)",
                            "severity": "medium",
                            "time": f_time,
                            "source": "threshold"
                        })

                # Precipitation start
                if f_rain > self.alert_thresholds["precipitation_start"] and "Rain" not in c_cond:
                    warnings.append({
                        "type": "rain_starting",
                        "message": f"☔ Rain expected around {f_label} ({f_rain:.1f}mm/h predicted)",
                        "severity": "medium",
                        "time": f_time,
                        "source": "threshold"
                    })

                # High winds
                if f_wind > self.alert_thresholds["wind_speed"]:
                    warnings.append({
                        "type": "high_wind",
                        "message": f"💨 Strong winds expected around {f_label} ({f_wind:.1f} m/s ≈ {f_wind * 3.6:.1f} km/h)",
                        "severity": "medium",
                        "time": f_time,
                        "source": "threshold"
                    })

                # Severe conditions (e.g. Thunderstorm/Snow)
                if c_cond != f_cond and f_cond in ["Thunderstorm", "Snow"]:
                    warnings.append({
                        "type": "severe_weather",
                        "message": f"⛈️ {f_cond} expected around {f_label}",
                        "severity": "high",
                        "time": f_time,
                        "source": "threshold"
                    })

        except Exception as e:
            print(f"⚠️ Error checking upcoming changes: {e}")

        return warnings

    def _should_send_alert(self, user_id: str, warning_type: str) -> bool:
        """
        Check if cooldown has elapsed since last_alert_time for this warning_type.
        """
        session = self.active_sessions.get(user_id)
        if not session:
            return False

        last = session.get("last_alert_time")
        if not last:
            return True

        cooldown_min = session.get("alert_cooldown", 30)
        elapsed_min = (datetime.now() - last).total_seconds() / 60
        return elapsed_min >= cooldown_min

    def monitor_all_users(self):
        """
        Main “infinite” loop: every self.check_interval seconds,
        look at all active_sessions, see if they have new warnings, send them.
        """
        while self.running:
            try:
                now = datetime.now()
                to_remove: List[str] = []

                for user_id, sess in list(self.active_sessions.items()):
                    # If session expired ⏰
                    if now > sess["end_time"]:
                        to_remove.append(user_id)
                        continue

                    # Check for warnings (list of dicts)
                    warnings = self.check_weather_changes(user_id, sess)
                    if warnings:
                        filt = self._filter_warnings(user_id, warnings)
                        if filt:
                            self._send_alerts(user_id, sess, filt)
                            sess["last_alert_time"] = now
                            sess["alert_count"] += len(filt)

                    sess["last_check"] = now

                # Clean up any expired sessions
                for uid in to_remove:
                    print(f"🗑️ Removing expired session for {uid}")
                    self._cleanup_expired_session(uid)

                time.sleep(self.check_interval)

            except Exception as e:
                print(f"❌ Error in monitoring loop: {e}")
                time.sleep(60)

    def _filter_warnings(self, user_id: str, warnings: List[Dict]) -> List[Dict]:
        """
        Given a list of potential warnings, only keep those above the user's severity threshold
        AND respecting the cooldown for that warning type.
        """
        session = self.active_sessions.get(user_id)
        if not session:
            return []

        pref = session.get("notification_prefs", {})
        thresh_level = pref.get("severity_threshold", "medium")
        levels = {"low": 1, "medium": 2, "high": 3}
        min_lvl = levels.get(thresh_level, 2)

        filtered: List[Dict] = []
        for w in warnings:
            lvl = levels.get(w.get("severity", "medium"), 2)
            if lvl >= min_lvl and self._should_send_alert(user_id, w["type"]):
                filtered.append(w)

        return filtered

    def _send_alerts(self, user_id: str, session_data: Dict, warnings: List[Dict]):
        """
        Send alerts via whichever channels are in session_data['notification_prefs'].
        Then log to DB + disk.
        """
        location = session_data["location_name"]
        prefs = session_data.get("notification_prefs", {})

        alert_title = f"Weather Alert for {location}"
        alert_body = "\n".join([w["message"] for w in warnings])

        # 1) Log to a per-user file if requested
        if prefs.get("log_file", True):
            self._log_alerts_to_file(user_id, location, warnings)

        # 2) Email
        if prefs.get("email", False) and session_data.get("email"):
            try:
                send_email_alert(
                    session_data["email"],
                    alert_title,
                    alert_body,
                    location
                )
                print(f"📧 Email alert sent to {session_data['email']}")
            except Exception as e:
                print(f"❌ Failed to send email to {session_data['email']}: {e}")

        # 3) Push (Firebase)
        if prefs.get("push", True):
            try:
                # In push_helper, send_push_notification now points to Firebase version
                send_push_notification(user_id, alert_title, alert_body)
                print(f"📱 Push notification sent to {user_id}")
            except Exception as e:
                print(f"❌ Failed to send push to {user_id}: {e}")

        # 4) Save to alert_history table
        self._save_alerts_to_history(user_id, warnings)

        # 5) Debug‐print to console
        print(f"🚨 ALERTS for {user_id} at {location}:")
        for w in warnings:
            emoji = {"low": "💡", "medium": "⚠️", "high": "🚨"}.get(w.get("severity", "medium"), "⚠️")
            print(f"  {emoji} {w['message']} [{w.get('source','unknown')}]")

    def _log_alerts_to_file(self, user_id: str, location: str, warnings: List[Dict]):
        """
        Append warnings → a per-user log file under folder “agent_alerts/”.
        """
        log_dir = "agent_alerts"
        os.makedirs(log_dir, exist_ok=True)
        safe_name = user_id.replace("@", "_at_")
        log_file = os.path.join(log_dir, f"{safe_name}.log")
        with open(log_file, "a") as f:
            f.write(f"\n=== {datetime.now().isoformat()} ===\n")
            f.write(f"📍 Location: {location}\n")
            for w in warnings:
                f.write(f"{w['message']} [Source: {w.get('source','unknown')}]\n")

    def _save_alerts_to_history(self, user_id: str, warnings: List[Dict]):
        """Insert each warning into the alert_history table."""
        with sqlite3.connect(self.db_path) as conn:
            for w in warnings:
                conn.execute("""
                    INSERT INTO alert_history (user_id, alert_type, message, severity)
                    VALUES (?, ?, ?, ?)
                """, (
                    user_id,
                    w["type"],
                    w["message"],
                    w.get("severity", "medium")
                ))

    def _cleanup_expired_session(self, user_id: str):
        """Remove user_id from memory + mark in DB as expired."""
        if user_id in self.active_sessions:
            del self.active_sessions[user_id]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE user_sessions
                SET end_time = ?
                WHERE user_id = ? 
                  AND end_time > ?
            """, (datetime.now().isoformat(), user_id, datetime.now().isoformat()))

    def start_monitoring(self):
        """
        Begin the background thread that calls self.monitor_all_users().
        If there were old sessions in the DB, reload them.
        """
        if not self.running:
            self._load_sessions_from_db()
            self.running = True
            self.monitor_thread = threading.Thread(target=self.monitor_all_users, daemon=True)
            self.monitor_thread.start()
            print("🤖 Weather Agent monitoring started")
            print(f"📊 Monitoring {len(self.active_sessions)} active session(s)")

    def stop_monitoring(self):
        """Stop the background monitoring thread."""
        self.running = False
        print("🛑 Weather Agent monitoring stopped")

    def get_user_status(self, user_id: str) -> Dict[str, Any]:
        """Return {status, location, monitoring_until, last_check, alert_count, notification_preferences}."""
        sess = self.active_sessions.get(user_id)
        if not sess:
            return {"status": "not_monitored"}

        return {
            "status": "active",
            "location": sess["location_name"],
            "monitoring_until": sess["end_time"].isoformat(),
            "last_check": sess["last_check"].isoformat(),
            "alert_count": sess.get("alert_count", 0),
            "notification_preferences": sess.get("notification_prefs", {}),
        }

    def get_alert_history(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch the most recent `limit` rows from alert_history for this user."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT alert_type, message, severity, sent_at
                FROM alert_history
                WHERE user_id = ?
                ORDER BY sent_at DESC
                LIMIT ?
            """, (user_id, limit))
            rows = cursor.fetchall()
            return [
                {
                    "type": row[0],
                    "message": row[1],
                    "severity": row[2],
                    "sent_at": row[3]
                }
                for row in rows
            ]

# Global singleton
weather_agent = WeatherAgent()

# ================================
# ‣ Flask‐exposed endpoints
# ================================

@weather_agent_bp.route("/start-agent", methods=["POST"])
def start_agent_endpoint():
    """
    POST /start-agent
    Body JSON: { user_id: str, lat: float, lon: float, duration_hours?: int, email?: str, notification_preferences?: object }
    """
    data = request.get_json() or {}
    req_fields = ["user_id", "lat", "lon"]
    if not all(f in data for f in req_fields):
        return jsonify({"error": "Missing required fields: user_id, lat, lon"}), 400

    result = weather_agent.register_user_session(
        user_id=data["user_id"],
        lat=float(data["lat"]),
        lon=float(data["lon"]),
        duration_hours=data.get("duration_hours", 6),
        email=data.get("email"),
        notification_prefs=data.get("notification_preferences")
    )
    return jsonify(result)

@weather_agent_bp.route("/stop-agent", methods=["POST"])
def stop_agent_endpoint():
    """
    POST /stop-agent
    Body JSON: { user_id: str }
    """
    data = request.get_json() or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    if user_id in weather_agent.active_sessions:
        weather_agent._cleanup_expired_session(user_id)
        return jsonify({"status": "stopped", "user_id": user_id})
    else:
        return jsonify({"status": "not_found", "user_id": user_id}), 404

@weather_agent_bp.route("/status/<string:user_id>", methods=["GET"])
def get_status_endpoint(user_id: str):
    """
    GET /status/<user_id>
    Returns monitoring status for that user (active vs not_monitored).
    """
    return jsonify(weather_agent.get_user_status(user_id))

@weather_agent_bp.route("/history/<string:user_id>", methods=["GET"])
def get_history_endpoint(user_id: str):
    """
    GET /history/<user_id>?limit=50
    Returns up to `limit` alerts from alert_history for that user.
    """
    limit = request.args.get("limit", 50, type=int)
    history = weather_agent.get_alert_history(user_id, limit)
    return jsonify({"user_id": user_id, "alerts": history})

@weather_agent_bp.route("/service/start", methods=["POST"])
def start_service_endpoint():
    """
    POST /service/start
    Manually start the background monitoring loop (if not already running).
    """
    if not weather_agent.running:
        weather_agent.start_monitoring()
        return jsonify({
            "status": "started",
            "active_sessions": len(weather_agent.active_sessions)
        })
    else:
        return jsonify({
            "status": "already_running",
            "active_sessions": len(weather_agent.active_sessions)
        })

@weather_agent_bp.route("/service/stop", methods=["POST"])
def stop_service_endpoint():
    """
    POST /service/stop
    Manually stop the background monitoring loop.
    """
    if weather_agent.running:
        weather_agent.stop_monitoring()
        return jsonify({"status": "stopped"})
    else:
        return jsonify({"status": "not_running"})

@weather_agent_bp.route("/service/status", methods=["GET"])
def service_status_endpoint():
    """
    GET /service/status
    Returns { running: bool, active_sessions: int, check_interval: int, gpt_analysis_enabled: bool }
    """
    return jsonify({
        "running": weather_agent.running,
        "active_sessions": len(weather_agent.active_sessions),
        "check_interval": weather_agent.check_interval,
        "gpt_analysis_enabled": weather_agent.gpt_analysis_enabled
    })

# ================================
# ‣ Helper to auto‐start
# ================================
def monitor_all_sessions_loop():
    """
    Entry point for main.py’s background thread.
    Instantiates the WeatherAgent and begins its monitoring loop.
    """
    weather_agent.start_monitoring()
    # Now the .monitor_all_users() thread is running in the background.
    # This function simply returns (the monitoring thread lives on).
    return weather_agent
