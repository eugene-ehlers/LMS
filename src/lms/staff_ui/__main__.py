"""Serve the staff screens on localhost.

    python -m lms.staff_ui
"""

from __future__ import annotations

import os

from lms.staff_ui.app import build_app, serve


def main() -> None:
    host = os.environ.get("STAFF_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("STAFF_UI_PORT", "8765"))
    serve(build_app(), host, port)


if __name__ == "__main__":
    main()
