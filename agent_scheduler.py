# agent_scheduler.py
# LEGACY SHIM: Delegate to weather_agent.monitor_all_sessions_loop()

from weather_agent import monitor_all_sessions_loop

def run_scheduler():
    """
    Legacy function name. Internally just starts the WeatherAgent loop.
    When this is called (e.g. by main.py), it spawns the background monitoring thread.
    """
    return monitor_all_sessions_loop()
