"""Windows desktop entry point: launch the existing Streamlit UI in a WebView window."""
from __future__ import annotations
import os, socket, subprocess, sys, time
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP = BASE / "app.py"
try:
    from dotenv import load_dotenv
    load_dotenv(Path(sys.executable).resolve().parent / ".env")
    load_dotenv(BASE / ".env")
except Exception:
    pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    try:
        import webview
        from streamlit.web import bootstrap
        import runtime_imports  # noqa: F401 — collect dynamically loaded app modules for PyInstaller
    except ImportError as exc:
        raise SystemExit("Desktop dependencies are missing. Rebuild with build_windows.bat.") from exc

    port = free_port()
    # Keep mutable DB/config files beside the executable, not inside PyInstaller's temp bundle.
    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    os.chdir(app_dir)
    flag_options = {
        "server.address": "127.0.0.1",
        "server.port": port,
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "server.fileWatcherType": "none",
    }

    import threading
    server_error = []
    def run_streamlit():
        try:
            bootstrap.run(str(APP), "", [], flag_options)
        except Exception as exc:
            server_error.append(exc)

    threading.Thread(target=run_streamlit, daemon=True, name="GovernmentAI-Streamlit").start()
    url = f"http://127.0.0.1:{port}"
    import urllib.request
    for _ in range(90):
        if server_error:
            raise RuntimeError(f"Government AI Platform server failed: {server_error[0]}")
        try:
            urllib.request.urlopen(url, timeout=1).close()
            break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError("Government AI Platform did not start within 90 seconds.")
    webview.create_window("Government AI Platform", url, width=1440, height=900, min_size=(1024, 700))
    webview.start()

if __name__ == "__main__":
    main()
