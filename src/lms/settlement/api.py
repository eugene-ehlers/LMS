"""POST /v1/settlement-readvances. No session middleware and no bank socket."""

from __future__ import annotations

from lms.settlement.service import SettlementReadvance


def dispatch(
    command: SettlementReadvance,
    method: str,
    path: str,
    body: dict | None,
    headers: dict | None,
) -> tuple[int, dict]:
    headers = headers or {}
    if method.upper() == "POST" and _parts(path) == ["v1", "settlement-readvances"]:
        key = headers.get("Idempotency-Key") or headers.get("idempotency-key") or ""
        return command.settle_and_readvance(body, key)
    return 404, {
        "outcome": "failure",
        "code": "not-found",
        "message": "No settlement re-advance route matches this request.",
    }


def _parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]
