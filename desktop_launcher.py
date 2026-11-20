"""Windows desktop entry point: launch the existing Streamlit UI in a WebView window."""

from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP = BASE / "app.py"
APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)

try:
    from dotenv import load_dotenv

    load_dotenv(APP_DIR / ".env")  # .env beside the exe / this script
    load_dotenv(BASE / ".env")
except Exception:
    pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _allow_streamlit_in_thread() -> None:
    """Streamlit registers signal handlers, which Python only allows on the main thread.
    Streamlit runs in a background thread here (the main thread is used by the window), so ignore them.
    """
    original = signal.signal

    def safe_signal(signum, handler):
        if threading.current_thread() is not threading.main_thread():
            return None
        return original(signum, handler)

    signal.signal = safe_signal


def main():
    try:
        import webview
        from streamlit.web import bootstrap
        import runtime_imports  # noqa: F401 - collect dynamically loaded app modules for PyInstaller
    except ImportError as exc:
        raise SystemExit(
            f"Desktop dependencies are missing ({exc}). Run: pip install -r requirements.txt"
        ) from exc

    os.chdir(APP_DIR)  # keep database.db / files beside the app, not in a temp folder
    _allow_streamlit_in_thread()

    port = free_port()
    flag_options = {
        "server.address": "127.0.0.1",
        "server.port": port,
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "server.fileWatcherType": "none",
    }
    server_error: list[Exception] = []

    def run_streamlit():
        try:
            bootstrap.run(str(APP), False, [], flag_options)
        except BaseException as exc:  # noqa: BLE001
            server_error.append(exc)

    threading.Thread(
        target=run_streamlit, daemon=True, name="GovernmentAI-Streamlit"
    ).start()

    url = f"http://127.0.0.1:{port}"
    for _ in range(90):
        if server_error:
            raise RuntimeError(
                f"Government AI Platform server failed: {server_error[0]!r}"
            )
        try:
            urllib.request.urlopen(url, timeout=1).close()
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError("Government AI Platform did not start within 90 seconds.")

    try:
        webview.create_window(
            "Government AI Platform", url, width=1440, height=900, min_size=(1024, 700)
        )
        webview.start()
    except (
        Exception
    ) as exc:  # no WebView2 runtime etc.: fall back to the default browser
        import webbrowser

        print(
            f"Desktop window unavailable ({exc}); opening {url} in your browser. Close this window to stop."
        )
        webbrowser.open(url)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
