#!/usr/bin/env python
"""Facial Attendance System - Web UI Launcher

Starts the local FastAPI backend with WebSocket stream and serves the React frontend.
Automatically opens your browser to http://127.0.0.1:8000.
"""

import argparse
import sys
import threading
import time
import webbrowser
import uvicorn


def open_browser(url: str, delay: float = 1.2) -> None:
    """Open default browser after server initializes."""
    time.sleep(delay)
    print(f"\n>>> Opening web interface: {url}")
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="Run Facial Attendance Web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    print("=" * 60)
    print(" FACIAL ATTENDANCE SYSTEM - WEB UI")
    print(f" URL: {url}")
    print("=" * 60)

    if not args.no_browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    uvicorn.run("app.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
