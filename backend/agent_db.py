# agent_db.py 🧠🐴
# Simple SQLite backend for storing weather agent data

import sqlite3
import json
from datetime import datetime, timezone

DB_NAME = "donkey_agents.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            location TEXT NOT NULL,
            reminder_times TEXT NOT NULL,  -- stored as JSON string
            timezone TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def add_agent(user_id, location, reminder_times, tz_string):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    now = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO agents (user_id, location, reminder_times, timezone, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, location, json.dumps(reminder_times), tz_string, now))
    conn.commit()
    conn.close()



def get_agents():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM agents")
    rows = cursor.fetchall()
    conn.close()

    agents = []
    for row in rows:
        agents.append({
            "id": row[0],
            "user_id": row[1],
            "location": row[2],
            "reminder_times": json.loads(row[3]),
            "timezone": row[4],
            "created_at": row[5]
        })
    return agents


def delete_agent(agent_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()


def update_agent(agent_id, new_times):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE agents SET reminder_times = ? WHERE id = ?
    """, (json.dumps(new_times), agent_id))
    conn.commit()
    conn.close()


# Initialize DB on import
init_db()
