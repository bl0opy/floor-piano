#!/usr/bin/env python3
"""
Simple HTTP server for the Piano Tiles game.

Usage:
    python server.py              # serves on http://localhost:8765
    python server.py --port 9000  # custom port
"""

import argparse
import http.server
import os
import socketserver
import webbrowser


DIR = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def log_message(self, fmt, *args):
        # Suppress per-request logs for cleaner output
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Piano Tiles game server")
    parser.add_argument("--port", type=int, default=8765, help="Port to serve on (default: 8765)")
    parser.add_argument("--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    with socketserver.TCPServer((args.host, args.port), Handler) as httpd:
        print(f"\n  Piano Tiles  --  {url}\n")
        print("  Controls:  A  S  D  F")
        print("  Press Ctrl+C to stop.\n")

        if not args.no_browser:
            webbrowser.open(url)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == "__main__":
    main()
