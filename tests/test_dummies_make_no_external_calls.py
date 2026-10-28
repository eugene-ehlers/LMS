from pathlib import Path


BANNED_SNIPPETS = (
    "import socket",
    "from socket",
    "import urllib",
    "from urllib",
    "import http.client",
    "import requests",
    "import httpx",
    "import aiohttp",
)


def test_lms_sources_do_not_import_network_clients() -> None:
    roots = [Path("lms")]
    sources = [path for root in roots for path in root.rglob("*.py")]
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for snippet in BANNED_SNIPPETS:
            assert snippet not in text, f"{path} contains {snippet}"
