# logger_config.py
# Centralized logging configuration for Mister Donkey backend

import logging
import sys
from datetime import datetime
import os

def setup_logger(name: str = "mister_donkey", log_level: str = None) -> logging.Logger:
    """
    Configure and return a logger instance with consistent formatting.

    Args:
        name: Logger name (default: "mister_donkey")
        log_level: Override log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                  If None, reads from ENV environment variable

    Returns:
        Configured logger instance
    """
    # Determine log level
    if log_level is None:
        env = os.getenv("ENV", "prod").strip().lower()
        log_level = "DEBUG" if env == "dev" else "INFO"

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Console handler with color-coded output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logger.level)

    # Format: [TIMESTAMP] [LEVEL] [MODULE] Message
    formatter = logging.Formatter(
        fmt='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    # Optional: File handler for persistent logs
    log_dir = os.getenv("LOG_DIR", "./logs")
    if os.path.exists(log_dir) or os.makedirs(log_dir, exist_ok=True):
        log_file = os.path.join(log_dir, f"mister_donkey_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# Create default logger instance
default_logger = setup_logger()


def log_api_call(endpoint: str, status: str, duration_ms: float, details: str = ""):
    """
    Log API call with standardized format.

    Args:
        endpoint: API endpoint called (e.g., "/prompt", "OpenWeather", "NewsAPI")
        status: "success" or "error"
        duration_ms: Request duration in milliseconds
        details: Additional context or error message
    """
    emoji = "✅" if status == "success" else "❌"
    logger = logging.getLogger("mister_donkey.api")

    message = f"{emoji} {endpoint} | {status.upper()} | {duration_ms:.0f}ms"
    if details:
        message += f" | {details}"

    if status == "success":
        logger.info(message)
    else:
        logger.error(message)


def log_llm_call(model: str, tokens: int, cost_estimate: float, status: str, details: str = ""):
    """
    Log LLM API call with token usage and cost tracking.

    Args:
        model: Model name (e.g., "gpt-4o-mini")
        tokens: Total tokens used
        cost_estimate: Estimated cost in USD
        status: "success" or "error"
        details: Additional context
    """
    logger = logging.getLogger("mister_donkey.llm")
    emoji = "🤖" if status == "success" else "❌"

    message = f"{emoji} {model} | {tokens} tokens | ${cost_estimate:.4f} | {status.upper()}"
    if details:
        message += f" | {details}"

    if status == "success":
        logger.info(message)
    else:
        logger.error(message)
