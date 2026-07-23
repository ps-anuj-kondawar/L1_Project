import logging
import contextvars
import sys

# ContextVar to store logs for the current request context (async/thread safe)
_request_logs = contextvars.ContextVar("request_logs", default=None)

class ContextLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        
        # 1. Save to context log list for UI display
        logs_list = _request_logs.get()
        if logs_list is not None:
            logs_list.append(msg)
            
        # 2. Print directly to stdout/console to bypass any Gradio/Uvicorn logging silencers
        sys.stdout.write(msg + "\n")
        sys.stdout.flush()

# Setup standard logger
logger = logging.getLogger("safety_auditor")
logger.setLevel(logging.INFO)

# Formatter for structured logging
formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", datefmt="%H:%M:%S")

# Context handler (stores logs in ContextVar and prints to console)
context_handler = ContextLogHandler()
context_handler.setFormatter(formatter)
logger.addHandler(context_handler)

def start_request_logging():
    """Initialize a fresh log list for the current request context."""
    _request_logs.set([])

def get_request_logs() -> list[str]:
    """Retrieve all log messages captured in the current request context."""
    logs = _request_logs.get()
    return logs if logs is not None else []
