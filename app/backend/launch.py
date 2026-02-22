"""Launch the dashboard as a native Mac app with pywebview."""

import logging
import sys
import threading
import time

import uvicorn
import webview

LOG_FILE = "/tmp/dashboard-backend.log"


def setup_logging():
    """Route all backend logs to the shared log file."""
    handler = logging.FileHandler(LOG_FILE, mode="a")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Also capture stdout/stderr so print() and tracebacks go to the log
    sys.stdout = open(LOG_FILE, "a")
    sys.stderr = open(LOG_FILE, "a")


def start_server():
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    setup_logging()

    # Start FastAPI in a background thread
    server = threading.Thread(target=start_server, daemon=True)
    server.start()

    # Wait for the server to be ready
    import urllib.request

    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/health")
            break
        except Exception:
            time.sleep(0.2)

    # Open native window
    window = webview.create_window(
        "Personal Dashboard",
        "http://127.0.0.1:8000",
        width=1280,
        height=860,
        min_size=(800, 600),
    )
    webview.start()
