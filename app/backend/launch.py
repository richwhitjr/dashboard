"""Launch the dashboard as a native Mac app with pywebview."""

import logging
import os
import platform
import sys
import threading
import time

import uvicorn
import webview

LOG_FILE = "/tmp/dashboard-backend.log"
log = logging.getLogger("launch")


def setup_logging():
    """Route all backend logs to the shared log file."""
    handler = logging.FileHandler(LOG_FILE, mode="a")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Also capture stdout/stderr so print() and tracebacks go to the log.
    # Use line-buffering (buffering=1) so output is flushed on every newline —
    # without this, crash output can be lost in an unflushed buffer.
    sys.stdout = open(LOG_FILE, "a", buffering=1)
    sys.stderr = open(LOG_FILE, "a", buffering=1)


def start_server():
    log.info("Starting uvicorn server on 127.0.0.1:8000")
    try:
        uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")
    except BaseException as e:
        # Catch BaseException to also capture SystemExit (raised by sys.exit())
        log.error("Uvicorn server crashed: %s: %s", type(e).__name__, e)
        import traceback
        log.error("".join(traceback.format_exc()))
        raise


if __name__ == "__main__":
    # In PyInstaller bundle, set cwd to _MEIPASS so module imports resolve correctly
    is_frozen = getattr(sys, "_MEIPASS", None) is not None
    if is_frozen:
        os.chdir(sys._MEIPASS)
        if sys._MEIPASS not in sys.path:
            sys.path.insert(0, sys._MEIPASS)

    setup_logging()

    log.info("=" * 60)
    log.info("Dashboard launch starting")
    log.info("  Python:     %s", sys.version)
    log.info("  Platform:   %s %s", platform.system(), platform.machine())
    log.info("  macOS:      %s", platform.mac_ver()[0])
    log.info("  Bundled:    %s", is_frozen)
    log.info("  MEIPASS:    %s", getattr(sys, "_MEIPASS", "N/A"))
    log.info("  CWD:        %s", os.getcwd())
    log.info("  HOME:       %s", os.path.expanduser("~"))
    log.info("  Data dir:   %s", os.environ.get("DASHBOARD_DATA_DIR", "~/.personal-dashboard"))
    log.info("=" * 60)

    # Check if frontend dist exists in the expected location
    if is_frozen:
        dist_path = os.path.join(sys._MEIPASS, "frontend", "dist")
    else:
        dist_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    dist_exists = os.path.isdir(dist_path)
    index_exists = os.path.isfile(os.path.join(dist_path, "index.html")) if dist_exists else False
    log.info("Frontend dist: %s (exists=%s, index.html=%s)", dist_path, dist_exists, index_exists)
    if dist_exists:
        try:
            contents = os.listdir(dist_path)
            log.info("Frontend dist contents: %s", contents)
        except Exception as e:
            log.warning("Could not list frontend dist: %s", e)

    # Check if port 8000 is already in use
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    port_in_use = sock.connect_ex(("127.0.0.1", 8000)) == 0
    sock.close()
    if port_in_use:
        log.warning("Port 8000 is already in use! Server may fail to start.")

    # Start FastAPI in a background thread
    log.info("Launching server thread...")
    server_error = threading.Event()

    def _server_wrapper():
        try:
            start_server()
        except BaseException as e:
            log.error("Server thread died: %s: %s", type(e).__name__, e)
            server_error.set()
        finally:
            # Ensure buffers are flushed even if thread dies
            sys.stdout.flush()
            sys.stderr.flush()

    server = threading.Thread(target=_server_wrapper, daemon=True)
    server.start()

    # Wait for the server to be ready
    import urllib.request

    log.info("Waiting for server health check...")
    server_ready = False
    for attempt in range(30):
        if server_error.is_set():
            log.error("Server thread crashed before becoming ready")
            break
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2)
            log.info("Server ready after %d attempts (%.1fs)", attempt + 1, attempt * 0.2)
            server_ready = True
            break
        except Exception as e:
            if attempt % 5 == 4:  # Log every 5th attempt
                log.info("  Health check attempt %d failed: %s", attempt + 1, e)
            time.sleep(0.2)

    if not server_ready:
        log.error("Server did not become ready after 30 attempts (6s). Opening window anyway.")

    # Open native window
    log.info("Creating pywebview window (1280x860)...")
    try:
        window = webview.create_window(
            "Personal Dashboard",
            "http://127.0.0.1:8000",
            width=1280,
            height=860,
            min_size=(800, 600),
        )
        log.info("Starting pywebview event loop")
        webview.start()
        log.info("pywebview event loop ended (window closed)")
    except Exception:
        log.exception("pywebview failed")
