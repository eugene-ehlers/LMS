"""HTTP query route for daily calculation batch status."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from lms.batch.errors import BatchError
from lms.batch.service import BatchService
from lms.batch.store import BatchStore

_STATUS_PATH = re.compile(r"^/organisations/([^/]+)/batch-status$")
_RUN_PATH = re.compile(r"^/organisations/([^/]+)/batch-runs$")
_SKIP_PATH = re.compile(r"^/organisations/([^/]+)/batch-runs/([^/]+)/skip$")


class BatchStatusApp:
    def __init__(self, service: BatchService) -> None:
        self._service = service

    def handle(
        self, method: str, path: str, body: bytes | None = None
    ) -> tuple[int, dict[str, object]]:
        split = urlsplit(path)
        if split.query:
            return 400, {"error": "this route does not accept a query string"}
        route = split.path
        status_match = _STATUS_PATH.fullmatch(route)
        if status_match:
            if method != "GET":
                return 405, {"error": "method not allowed"}
            return self._status(unquote(status_match.group(1)))
        run_match = _RUN_PATH.fullmatch(route)
        if run_match:
            if method != "POST":
                return 405, {"error": "method not allowed"}
            return self._run(unquote(run_match.group(1)), body)
        skip_match = _SKIP_PATH.fullmatch(route)
        if skip_match:
            if method != "POST":
                return 405, {"error": "method not allowed"}
            return self._skip(
                unquote(skip_match.group(1)),
                unquote(skip_match.group(2)),
                body,
            )
        return 404, {"error": "route not found"}

    def _status(self, organisation_id: str) -> tuple[int, dict[str, object]]:
        try:
            status = self._service.status(organisation_id)
        except BatchError as exc:
            return exc.status_code, _error_body(exc)
        return 200, status.to_dict()

    def _run(
        self, organisation_id: str, body: bytes | None
    ) -> tuple[int, dict[str, object]]:
        payload, error = _object_body(body)
        if error is not None:
            return 400, {"error": error}
        if _conflicts(payload, organisation_id):
            return 400, {
                "error": "organisation_id in the body does not match the route"
            }
        try:
            run = self._service.run_batch(
                organisation_id=organisation_id,
                actor_id=payload.get("actor_id", ""),
                recognition_date=payload.get("recognition_date", ""),
                account_ids=payload.get("account_ids", None),
            )
        except BatchError as exc:
            return exc.status_code, _error_body(exc)
        code = 201 if run.outcome == "success" else 200
        return code, run.to_dict()

    def _skip(
        self, organisation_id: str, run_id: str, body: bytes | None
    ) -> tuple[int, dict[str, object]]:
        payload, error = _object_body(body)
        if error is not None:
            return 400, {"error": error}
        if _conflicts(payload, organisation_id):
            return 400, {
                "error": "organisation_id in the body does not match the route"
            }
        try:
            run = self._service.skip_run(
                organisation_id=organisation_id,
                run_id=run_id,
                actor_id=payload.get("actor_id", ""),
                reason=payload.get("reason", ""),
            )
        except BatchError as exc:
            return exc.status_code, _error_body(exc)
        return 200, run.to_dict()


def build_app(
    database_path: str,
    calculation: object | None = None,
    clock: object | None = None,
    faults: set[str] | None = None,
) -> BatchStatusApp:
    store = BatchStore(database_path, faults=faults)
    service = BatchService(store, calculation, clock)
    return BatchStatusApp(service)


def serve(app: BatchStatusApp, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            status, payload = app.handle(method, self.path, raw)
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    return server


def _object_body(body: bytes | None) -> tuple[dict[str, object], str | None]:
    if body is None or body == b"":
        return {}, None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, "request body must be a JSON object"
    if not isinstance(parsed, dict):
        return {}, "request body must be a JSON object"
    return parsed, None


def _conflicts(payload: dict[str, object], organisation_id: str) -> bool:
    supplied = payload.get("organisation_id")
    return isinstance(supplied, str) and supplied != organisation_id


def _error_body(exc: BatchError) -> dict[str, object]:
    body: dict[str, object] = {"error": exc.reason}
    if exc.run is not None:
        body["run"] = exc.run.to_dict()
    return body
