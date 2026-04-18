#!/usr/bin/env python3
"""

Run this file to start!

Entry point for the Floor Piano application.

Usage:
    python run.py [--host HOST] [--port PORT] [--reload]

Examples:
    python run.py
    python run.py --port 8080
    python run.py --reload          # auto-reload on code changes (dev mode)
"""

import argparse
import sys
from pathlib import Path

# Ensure the project root is on the Python path so that `backend.*` imports work
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Floor Piano server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on file changes (dev mode)")
    args = parser.parse_args()

    print(f"\n  🎹  Floor Piano  —  http://{args.host}:{args.port}\n")

    uvicorn.run(
        "backend.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
