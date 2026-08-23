"""Logging and Rich console output utilities."""

import logging
from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "highlight": "bold magenta",
    "question": "bold white on blue",
    "option": "italic cyan",
    "score": "bold green on black",
})

console = Console(theme=custom_theme)

def setup_logger(name: str = "QuizAuto", log_level: str = "INFO") -> logging.Logger:
    """Setup and return a styled logger using RichHandler."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Remove existing handlers if any to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()
        
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    rich_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(rich_handler)
    return logger

log = setup_logger()
