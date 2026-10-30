"""Serve the daily batch status route.

Runs refuse to start until a daily calculation implementation is injected.
The query route still answers.
"""

from __future__ import annotations

import argparse

from lms.batch.api import build_app, serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily calculation batch status")
    parser.add_argument("--database", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    app = build_app(args.database)
    server = serve(app, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
