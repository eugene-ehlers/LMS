"""Staff screens. Every change calls an existing route and reports the outcome.

The screen does not price a campaign, resolve an election, or apply a
collection campaign itself. Those commands stay in the route modules.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from lms.collection_campaigns.api import dispatch as collection_dispatch
from lms.collection_campaigns.models import FEE_TYPES, ROLE as COLLECTION_ROLE
from lms.collection_campaigns.service import CollectionCampaigns
from lms.ledger.service import Ledger
from lms.regulatory.audit import AuditLog
from lms.regulatory.errors import RegulatoryError
from lms.staff.api import dispatch as staff_dispatch
from lms.staff.service import StaffOffice
from lms.staff_ui.access import SessionAccess
from lms.staff_ui import render

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")

BATCH_GAP = (
    "No daily-calculation batch route is registered. The audit extract was read "
    "and it contains no batch run. Last successful run: none recorded. "
    "Last failed run: none recorded. Failure reasons: none recorded. "
    "This screen does not accrue, capitalise, or flag a default."
)

_AUDIT_FROM = "1970-01-01"
_AUDIT_TO = "9999-12-31"


@dataclass
class Page:
    status: int
    body: str


@dataclass(frozen=True)
class PendingFailure:
    nonce: str
    action: str
    code: str
    message: str
    status: int
    return_to: str


class Session:
    def __init__(self) -> None:
        self.person_id = ""
        self.organisation_id = ""
        self.roles: frozenset[str] = frozenset()
        self.enigma_status = "active"
        self.pending: PendingFailure | None = None


class StaffApp:
    def __init__(self, office: StaffOffice, campaigns: CollectionCampaigns, access: SessionAccess) -> None:
        self.office = office
        self.campaigns = campaigns
        self.access = access
        self.sessions: dict[str, Session] = {}

    def handle(
        self,
        session: Session,
        method: str,
        path: str,
        form: dict | None = None,
        query: dict | None = None,
    ) -> Page:
        method = method.upper()
        form = form or {}
        query = query or {}
        parts = [part for part in urlsplit(path).path.split("/") if part]
        if session.pending is not None and not (method == "POST" and parts == ["staff", "acknowledge"]):
            if method == "POST":
                self._report(
                    session,
                    form,
                    action=path,
                    outcome="blocked",
                    status=session.pending.status,
                    code=session.pending.code,
                    message=session.pending.message,
                )
            return self._failure_page(session, "")
        if parts == ["staff", "acknowledge"] and method == "POST":
            return self._acknowledge(session, form)
        if parts[:2] == ["staff", "register"]:
            return self._out_of_scope(
                session, method, form,
                "Consumer registration is not an LMS screen. Decision 15 directs the consumer to Enigma.",
                "/staff/",
            )
        if parts[:2] == ["staff", "collection-notices"]:
            return self._out_of_scope(
                session, method, form,
                "The LMS does not generate collection notices. Decision 27 leaves them with the collections software.",
                "/staff/",
            )
        if parts[:2] == ["staff", "push"]:
            return self._out_of_scope(
                session, method, form,
                "Real push-provider integration is not a staff screen.",
                "/staff/",
            )
        if parts in (["staff"], []) and method == "GET":
            return self._view(session, "Staff session", render.home(session))
        if parts == ["staff", "session"] and method == "POST":
            self._save_session(session, form)
            return self._view(session, "Enigma session held", render.session_saved(), show_nav=False)
        if parts == ["staff", "campaigns"] and method == "GET":
            return self._campaign_list(session)
        if parts == ["staff", "campaigns", "new"] and method == "GET":
            return self._view(session, "Create campaign", render.campaign_form("/staff/campaigns", None, heading="Create a campaign"))
        if parts == ["staff", "campaigns"] and method == "POST":
            return self._campaign_write(session, form, None)
        if len(parts) == 4 and parts[:2] == ["staff", "campaigns"] and parts[3] == "end" and method == "POST":
            return self._campaign_end(session, form, parts[2])
        if len(parts) == 3 and parts[:2] == ["staff", "campaigns"] and method == "GET":
            return self._campaign_detail(session, parts[2])
        if len(parts) == 3 and parts[:2] == ["staff", "campaigns"] and method == "POST":
            return self._campaign_write(session, form, parts[2])
        if parts == ["staff", "elections"] and method == "GET":
            return self._election_list(session)
        if parts == ["staff", "elections"] and method == "POST":
            return self._election_write(session, form, None)
        if parts == ["staff", "products", "open"] and method == "GET":
            return self._open_product(session, query)
        if len(parts) == 4 and parts[:2] == ["staff", "products"] and parts[3] == "elections" and method == "GET":
            return self._election_product(session, parts[2])
        if len(parts) == 4 and parts[:2] == ["staff", "products"] and parts[3] == "elections" and method == "POST":
            return self._election_write(session, form, parts[2])
        if parts == ["staff", "compliance"] and method == "GET":
            return self._compliance_get(session)
        if parts == ["staff", "compliance"] and method == "POST":
            return self._compliance_put(session, form)
        if parts == ["staff", "ceilings", "platform"] and method == "GET":
            return self._ceiling_get(session, "platform")
        if parts == ["staff", "ceilings", "platform"] and method == "POST":
            return self._ceiling_put(session, form, "platform")
        if parts == ["staff", "ceilings", "company"] and method == "GET":
            return self._ceiling_get(session, "company")
        if parts == ["staff", "ceilings", "company"] and method == "POST":
            return self._ceiling_put(session, form, "company")
        if parts == ["staff", "ceilings", "check"] and method == "POST":
            return self._ceiling_check(session, form)
        if parts == ["staff", "collection-campaigns"] and method == "GET":
            return self._collection_list(session)
        if parts == ["staff", "collection-campaigns", "new"] and method == "GET":
            return self._view(
                session,
                "Create collection campaign",
                render.collection_form("/staff/collection-campaigns", None, heading="Create a collection campaign"),
            )
        if parts == ["staff", "collection-campaigns"] and method == "POST":
            return self._collection_save(session, form, None)
        if len(parts) == 4 and parts[:2] == ["staff", "collection-campaigns"] and parts[3] == "end" and method == "POST":
            return self._collection_end(session, form, parts[2])
        if len(parts) == 4 and parts[:2] == ["staff", "collection-campaigns"] and parts[3] == "apply" and method == "GET":
            gated = self._collection_read_gate(session, "collection-apply", f"/staff/collection-campaigns/{parts[2]}/apply")
            if gated is not None:
                return gated
            return self._view(session, "Apply collection campaign", render.collection_apply_form(parts[2]))
        if len(parts) == 4 and parts[:2] == ["staff", "collection-campaigns"] and parts[3] == "apply" and method == "POST":
            return self._collection_apply(session, form, parts[2])
        if len(parts) == 3 and parts[:2] == ["staff", "collection-campaigns"] and method == "GET":
            return self._collection_detail(session, parts[2])
        if len(parts) == 3 and parts[:2] == ["staff", "collection-campaigns"] and method == "POST":
            return self._collection_save(session, form, parts[2])
        if parts == ["staff", "batch"] and method == "GET":
            return self._batch(session)
        if method == "POST":
            return self._fail(
                session, form, action=path, status=404, code="not-found",
                message=f"No staff screen accepts {method} {path}.",
                return_to="/staff/",
            )
        return self._view(session, "Not found", render.plain("Not found", f"No staff screen at {path}."), status=404)

    def _campaign_list(self, session: Session) -> Page:
        org = _segment(session.organisation_id)
        if org is None:
            return self._fail(
                session, {}, action="campaign-list", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the campaign route cannot be addressed.",
                return_to="/staff/campaigns",
            )
        status, payload = self._staff(session, "GET", f"/v1/staff/organisations/{org}/campaigns", {})
        if status != 200:
            return self._route_fail(session, {}, "campaign-list", status, payload, "/staff/campaigns")
        return self._view(session, "Campaigns", render.campaign_list(payload.get("campaigns") or []))

    def _campaign_detail(self, session: Session, campaign_id: str) -> Page:
        org = _segment(session.organisation_id)
        if org is None:
            return self._fail(
                session, {}, action="campaign-read", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the campaign route cannot be addressed.",
                return_to="/staff/campaigns",
            )
        status, payload = self._staff(session, "GET", f"/v1/staff/organisations/{org}/campaigns/{campaign_id}", {})
        if status != 200:
            return self._route_fail(session, {}, "campaign-read", status, payload, "/staff/campaigns")
        inner = render.campaign_form(
            f"/staff/campaigns/{campaign_id}", payload, heading="Edit campaign",
        ) + render.campaign_end_form(campaign_id)
        return self._view(session, "Edit campaign", inner)

    def _campaign_write(self, session: Session, form: dict, campaign_id: str | None) -> Page:
        org = _segment(session.organisation_id)
        return_to = "/staff/campaigns/new" if campaign_id is None else f"/staff/campaigns/{campaign_id}"
        if org is None:
            return self._fail(
                session, form, action="campaign-save", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the campaign route cannot be addressed.",
                return_to=return_to,
            )
        body = _campaign_body(form)
        if campaign_id is None:
            status, payload = self._staff(session, "POST", f"/v1/staff/organisations/{org}/campaigns", body)
            action = "campaign-create"
        else:
            status, payload = self._staff(session, "PATCH", f"/v1/staff/organisations/{org}/campaigns/{campaign_id}", body)
            action = "campaign-edit"
        if status != 200:
            return self._route_fail(session, form, action, status, payload, return_to)
        summary = (
            f"Campaign {payload.get('campaign_id')} was stored. "
            f"Net rate is {payload.get('net_rate')}. Version is {payload.get('version')}. You can continue."
        )
        return self._ok(session, form, action, payload, summary, "/staff/campaigns")

    def _campaign_end(self, session: Session, form: dict, campaign_id: str) -> Page:
        org = _segment(session.organisation_id)
        return_to = f"/staff/campaigns/{campaign_id}"
        if org is None:
            return self._fail(
                session, form, action="campaign-end", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the campaign route cannot be addressed.",
                return_to=return_to,
            )
        status, payload = self._staff(
            session, "POST", f"/v1/staff/organisations/{org}/campaigns/{campaign_id}/end",
            {"recognised_at": form.get("recognised_at", "")},
        )
        if status != 200:
            return self._route_fail(session, form, "campaign-end", status, payload, return_to)
        summary = (
            f"Campaign {payload.get('campaign_id')} now ends on {payload.get('end_date')}. "
            f"Version is {payload.get('version')}. You can continue."
        )
        return self._ok(session, form, "campaign-end", payload, summary, "/staff/campaigns")

    def _election_list(self, session: Session) -> Page:
        org = _segment(session.organisation_id)
        if org is None:
            return self._fail(
                session, {}, action="election-list", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the election route cannot be addressed.",
                return_to="/staff/elections",
            )
        status, payload = self._staff(session, "GET", f"/v1/staff/organisations/{org}/elections", {})
        if status != 200:
            return self._route_fail(session, {}, "election-list", status, payload, "/staff/elections")
        return self._view(
            session, "Elections",
            render.election_list(payload.get("organisation") or {}, payload.get("products") or []),
        )

    def _election_product(self, session: Session, product_id: str) -> Page:
        org = _segment(session.organisation_id)
        if org is None or _segment(product_id) is None:
            return self._fail(
                session, {}, action="election-read", status=422, code="organisation-unset",
                message="The organisation id or product id is missing or contains a slash, so the election route cannot be addressed.",
                return_to="/staff/elections",
            )
        status, payload = self._staff(
            session, "GET", f"/v1/staff/organisations/{org}/products/{product_id}/elections", {},
        )
        if status != 200:
            return self._route_fail(session, {}, "election-read", status, payload, "/staff/elections")
        inner = render.election_form(
            f"/staff/products/{product_id}/elections", payload, heading=f"Product {product_id}",
        )
        return self._view(session, "Product elections", inner)

    def _open_product(self, session: Session, query: dict) -> Page:
        product_id = query.get("product_id", "").strip()
        if _segment(product_id) is None:
            return self._fail(
                session, {}, action="election-open", status=422, code="product-unset",
                message="A product id is required, and it cannot contain a slash.",
                return_to="/staff/elections",
            )
        return self._election_product(session, product_id)

    def _election_write(self, session: Session, form: dict, product_id: str | None) -> Page:
        org = _segment(session.organisation_id)
        if product_id is None:
            action = "election-edit"
            return_to = "/staff/elections"
            continue_href = "/staff/elections"
            path = None if org is None else f"/v1/staff/organisations/{org}/elections"
            summary = "The organisation elections were stored. You can continue."
        else:
            action = "product-election-edit"
            return_to = f"/staff/products/{product_id}/elections"
            continue_href = "/staff/elections"
            path = None if org is None or _segment(product_id) is None else (
                f"/v1/staff/organisations/{org}/products/{product_id}/elections"
            )
            summary = f"The product elections for {product_id} were stored. You can continue."
        if path is None:
            return self._fail(
                session, form, action=action, status=422, code="organisation-unset",
                message="The organisation id or product id is missing or contains a slash, so the election route cannot be addressed.",
                return_to=return_to,
            )
        status, payload = self._staff(session, "PUT", path, _election_body(form))
        if status != 200:
            return self._route_fail(session, form, action, status, payload, return_to)
        return self._ok(session, form, action, payload, summary, continue_href)

    def _compliance_get(self, session: Session) -> Page:
        org = _segment(session.organisation_id)
        if org is None:
            return self._fail(
                session, {}, action="compliance-read", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the compliance route cannot be addressed.",
                return_to="/staff/compliance",
            )
        status, payload = self._staff(session, "GET", f"/v1/staff/organisations/{org}/compliance", {})
        if status != 200:
            message = str(payload.get("message") or "")
            if "compliance-missing" in message:
                return self._view(
                    session, "Compliance details",
                    render.compliance_form({}, f"No compliance row is stored yet. {message}"),
                )
            return self._route_fail(session, {}, "compliance-read", status, payload, "/staff/compliance")
        return self._view(session, "Compliance details", render.compliance_form(payload, ""))

    def _compliance_put(self, session: Session, form: dict) -> Page:
        org = _segment(session.organisation_id)
        if org is None:
            return self._fail(
                session, form, action="compliance-edit", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the compliance route cannot be addressed.",
                return_to="/staff/compliance",
            )
        status, payload = self._staff(
            session, "PUT", f"/v1/staff/organisations/{org}/compliance", _compliance_body(form),
        )
        if status != 200:
            return self._route_fail(session, form, "compliance-edit", status, payload, "/staff/compliance")
        summary = (
            f"Compliance details were stored for {payload.get('organisation_id')}. "
            f"The NCR registration number is {payload.get('ncr_registration_number')}. You can continue."
        )
        return self._ok(session, form, "compliance-edit", payload, summary, "/staff/compliance")

    def _ceiling_get(self, session: Session, scope: str) -> Page:
        if scope == "platform":
            status, payload = self._staff(session, "GET", "/v1/staff/ceilings/platform", {})
            action = "/staff/ceilings/platform"
            title = "Solution-wide ceiling"
            check = False
        else:
            org = _segment(session.organisation_id)
            if org is None:
                return self._fail(
                    session, {}, action="ceiling-list", status=422, code="organisation-unset",
                    message="The Enigma organisation id is missing or contains a slash, so the ceiling route cannot be addressed.",
                    return_to="/staff/ceilings/company",
                )
            status, payload = self._staff(session, "GET", f"/v1/staff/organisations/{org}/ceilings", {})
            action = "/staff/ceilings/company"
            title = "Company ceiling"
            check = True
        if status != 200:
            return self._route_fail(session, {}, "ceiling-list", status, payload, action)
        return self._view(
            session, title,
            render.ceiling_page(scope=title, action=action, rows=payload.get("ceilings") or [], check=check),
        )

    def _ceiling_put(self, session: Session, form: dict, scope: str) -> Page:
        body = {
            "recognised_at": form.get("recognised_at", ""),
            "action": form.get("action", "").strip(),
            "amount_cents": _cents(form.get("amount_cents", "")),
        }
        if scope == "platform":
            status, payload = self._staff(session, "PUT", "/v1/staff/ceilings/platform", body)
            return_to = "/staff/ceilings/platform"
            action = "platform-ceiling"
        else:
            org = _segment(session.organisation_id)
            return_to = "/staff/ceilings/company"
            if org is None:
                return self._fail(
                    session, form, action="company-ceiling", status=422, code="organisation-unset",
                    message="The Enigma organisation id is missing or contains a slash, so the ceiling route cannot be addressed.",
                    return_to=return_to,
                )
            status, payload = self._staff(session, "PUT", f"/v1/staff/organisations/{org}/ceilings", body)
            action = "company-ceiling"
        if status != 200:
            return self._route_fail(session, form, action, status, payload, return_to)
        cents = payload.get("amount_cents")
        summary = (
            f"The {payload.get('scope')} ceiling for {payload.get('action')} is {cents} cents"
            f"{_rand_clause(cents)}. You can continue."
        )
        return self._ok(session, form, action, payload, summary, return_to)

    def _ceiling_check(self, session: Session, form: dict) -> Page:
        body = {
            "action": form.get("action", "").strip(),
            "amount_cents": _cents(form.get("amount_cents", "")),
            "organisation_id": form.get("organisation_id", "").strip(),
        }
        status, payload = self._staff(session, "POST", "/v1/staff/ceilings/apply", body)
        if status != 200:
            return self._route_fail(session, form, "ceiling-check", status, payload, "/staff/ceilings/company")
        summary = (
            f"The amount {payload.get('amount_cents')} cents is within the tighter ceiling of "
            f"{payload.get('limit_cents')} cents. Platform is {payload.get('platform_cents')} cents and "
            f"company is {payload.get('company_cents')} cents. Nothing was posted. You can continue."
        )
        return self._ok(session, form, "ceiling-check", payload, summary, "/staff/ceilings/company")

    def _collection_list(self, session: Session) -> Page:
        gated = self._collection_read_gate(session, "collection-list", "/staff/collection-campaigns")
        if gated is not None:
            return gated
        rows = [
            campaign
            for campaign in self.campaigns.campaigns.values()
            if campaign.organisation_id == session.organisation_id
        ]
        rows.sort(key=lambda campaign: (campaign.start_date.isoformat(), campaign.campaign_id))
        return self._view(session, "Collection campaigns", render.collection_list(rows))

    def _collection_detail(self, session: Session, campaign_id: str) -> Page:
        gated = self._collection_read_gate(session, "collection-read", "/staff/collection-campaigns")
        if gated is not None:
            return gated
        campaign = self._held(session, campaign_id)
        if campaign is None:
            return self._fail(
                session, {}, action="collection-read", status=404, code="campaign-unknown",
                message="That collection campaign is not held for this organisation. The route has no read method.",
                return_to="/staff/collection-campaigns",
            )
        values = _collection_values(campaign)
        inner = (
            render.collection_form(
                f"/staff/collection-campaigns/{campaign_id}", values, heading="Edit collection campaign",
            )
            + render.collection_end_form(campaign_id)
            + f'<p><a href="/staff/collection-campaigns/{render.esc(campaign_id)}/apply">Apply this campaign</a></p>'
        )
        return self._view(session, "Edit collection campaign", inner)

    def _collection_save(self, session: Session, form: dict, campaign_id: str | None) -> Page:
        return_to = "/staff/collection-campaigns/new" if campaign_id is None else f"/staff/collection-campaigns/{campaign_id}"
        action = "collection-create" if campaign_id is None else "collection-edit"
        blocked = self._collection_role_block(session, form, action, return_to)
        if blocked is not None:
            return blocked
        body = _collection_body(form, session.organisation_id)
        if campaign_id is None:
            status, payload = self._collection(session, "POST", "/v1/collection-campaigns", body)
        else:
            status, payload = self._collection(session, "POST", f"/v1/collection-campaigns/{campaign_id}", body)
        if status != 200:
            return self._route_fail(session, form, action, status, payload, return_to)
        end = payload.get("end_date") or "open-ended"
        summary = (
            f"Collection campaign {payload.get('campaign_id')} was stored. "
            f"It runs from {payload.get('start_date')} to {end}. You can continue."
        )
        return self._ok(session, form, action, payload, summary, "/staff/collection-campaigns")

    def _collection_end(self, session: Session, form: dict, campaign_id: str) -> Page:
        return_to = f"/staff/collection-campaigns/{campaign_id}"
        blocked = self._collection_role_block(session, form, "collection-end", return_to)
        if blocked is not None:
            return blocked
        body = {
            "organisation_id": session.organisation_id,
            "recognised_at": form.get("recognised_at", ""),
            "end_date": form.get("end_date", "").strip(),
        }
        status, payload = self._collection(session, "POST", f"/v1/collection-campaigns/{campaign_id}/end", body)
        if status != 200:
            return self._route_fail(session, form, "collection-end", status, payload, return_to)
        summary = (
            f"Collection campaign {payload.get('campaign_id')} now ends on {payload.get('end_date')}. "
            "You can continue."
        )
        return self._ok(session, form, "collection-end", payload, summary, "/staff/collection-campaigns")

    def _collection_apply(self, session: Session, form: dict, campaign_id: str) -> Page:
        return_to = f"/staff/collection-campaigns/{campaign_id}/apply"
        org = _segment(session.organisation_id)
        blocked = self._collection_role_block(session, form, "collection-apply", return_to)
        if blocked is not None:
            return blocked
        if org is None:
            return self._fail(
                session, form, action="collection-apply", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the apply route cannot be addressed.",
                return_to=return_to,
            )
        status, payload = self._collection(
            session, "POST",
            f"/v1/organisations/{org}/collection-campaigns/{campaign_id}/applications",
            _apply_body(form),
        )
        if status != 200:
            return self._route_fail(session, form, "collection-apply", status, payload, return_to)
        summary = f"The collection campaign was applied to {payload.get('count')} account(s). You can continue."
        return self._ok(session, form, "collection-apply", payload, summary, f"/staff/collection-campaigns/{campaign_id}")

    def _batch(self, session: Session) -> Page:
        org = _segment(session.organisation_id)
        if org is None:
            return self._fail(
                session, {}, action="batch-status", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing or contains a slash, so the audit route cannot be addressed.",
                return_to="/staff/batch",
            )
        status, payload = self._staff(
            session, "GET", f"/v1/staff/organisations/{org}/audit",
            {"from": _AUDIT_FROM, "to": _AUDIT_TO},
        )
        if status != 200:
            return self._route_fail(session, {}, "batch-status", status, payload, "/staff/batch")
        succeeded, failed = _split_batch(payload.get("rows") or [])
        return self._view(session, "Batch status", render.batch_status(succeeded, failed, gap=BATCH_GAP))

    def _collection_read_gate(self, session: Session, action: str, return_to: str) -> Page | None:
        """The list and the edit form have no route to call.

        A timeout, a suspended enrolment, an ambiguous status, or a missing
        role stops the read.
        """
        if not session.organisation_id.strip():
            return self._fail(
                session, {}, action=action, status=422, code="organisation-unset",
                message="A collection-campaign screen needs the Enigma organisation id.",
                return_to=return_to,
            )
        if session.enigma_status == "timeout":
            return self._fail(
                session, {}, action=action, status=503, code="authority-unavailable",
                message="LOCKED_DECISIONS §15: Enigma timed out. The collection campaign screen was not opened.",
                return_to=return_to,
            )
        if session.enigma_status == "suspended":
            return self._fail(
                session, {}, action=action, status=403, code="enrolment-suspended",
                message="LOCKED_DECISIONS §15: the enrolment is suspended. The collection campaign screen was not opened.",
                return_to=return_to,
            )
        if session.enigma_status != "active":
            return self._fail(
                session, {}, action=action, status=503, code="authority-ambiguous",
                message="LOCKED_DECISIONS §15: Enigma status is ambiguous. The collection campaign screen was not opened.",
                return_to=return_to,
            )
        return self._collection_role_block(session, {}, action, return_to)

    def _collection_role_block(self, session: Session, form: dict, action: str, return_to: str) -> Page | None:
        """The route reports a missing role as an ambiguous Enigma status.

        That message names the wrong cause. The screen states the missing role
        and does not call the route. Timeout and a suspended enrolment still
        go to the route.
        """
        if session.enigma_status != "active":
            return None
        if not session.person_id.strip() or not session.organisation_id.strip():
            return None
        if COLLECTION_ROLE in session.roles:
            return None
        return self._fail(
            session, form, action=action, status=403, code="mandate-denied",
            message=f"The Enigma enrolment does not include {COLLECTION_ROLE}.",
            return_to=return_to,
        )

    def _held(self, session: Session, campaign_id: str):
        campaign = self.campaigns.campaigns.get(campaign_id)
        if campaign is None or campaign.organisation_id != session.organisation_id:
            return None
        return campaign

    def _staff(self, session: Session, method: str, path: str, body: dict) -> tuple[int, dict]:
        status, payload = staff_dispatch(self.office, method, path, body, _headers(session))
        if not isinstance(payload, dict):
            return status, {"message": str(payload)}
        return status, payload

    def _collection(self, session: Session, method: str, path: str, body: dict) -> tuple[int, dict]:
        self.access.current = session
        try:
            status, payload = collection_dispatch(
                self.campaigns, method, path, body, {"X-Actor-Id": session.person_id},
            )
        finally:
            self.access.current = None
        if not isinstance(payload, dict):
            return status, {"message": str(payload)}
        return status, payload

    def _ok(self, session, form, action, payload, summary, continue_href) -> Page:
        note = self._report(session, form, action, "success", 200, "ok", summary)
        return self._view(session, "Confirmed", render.success(summary, payload, continue_href, note), show_nav=False)

    def _route_fail(self, session, form, action, status, payload, return_to) -> Page:
        return self._fail(
            session, form, action=action, status=status,
            code=str(payload.get("code") or ""),
            message=str(payload.get("message") or ""),
            return_to=return_to,
        )

    def _fail(self, session, form, *, action, status, code, message, return_to) -> Page:
        if not message:
            message = f"The route returned status {status} without a reason."
        note = self._report(session, form, action, "failure", status, code or "unspecified", message)
        session.pending = PendingFailure(
            nonce=secrets.token_urlsafe(12),
            action=action,
            code=code or "unspecified",
            message=message,
            status=status,
            return_to=return_to,
        )
        return self._failure_page(session, note)

    def _failure_page(self, session: Session, audit_note: str) -> Page:
        pending = session.pending
        assert pending is not None
        return self._view(
            session, "This step did not succeed", render.failure(pending, audit_note), show_nav=False, status=422,
        )

    def _acknowledge(self, session: Session, form: dict) -> Page:
        pending = session.pending
        if pending is None:
            return self._view(session, "Nothing to acknowledge", render.plain(
                "Nothing to acknowledge", "There is no failure waiting for acknowledgement.",
            ))
        if form.get("nonce") != pending.nonce:
            return self._failure_page(session, "")
        session.pending = None
        self._report(
            session, form, action="acknowledge", outcome="acknowledged",
            status=200, code=pending.code, message=pending.message,
        )
        return self._view(session, "Failure acknowledged", render.acknowledged(pending))

    def _out_of_scope(self, session, method, form, message, return_to) -> Page:
        if method == "POST":
            return self._fail(
                session, form, action=return_to, status=404, code="out-of-scope",
                message=message, return_to=return_to,
            )
        return self._view(session, "Not an LMS screen", render.plain("Not an LMS screen", message), status=404)

    def _view(self, session, title, inner, *, show_nav=True, status=200) -> Page:
        return Page(status, render.document(title, session, inner, show_nav=show_nav))

    def _save_session(self, session: Session, form: dict) -> None:
        session.person_id = form.get("person_id", "").strip()
        session.organisation_id = form.get("organisation_id", "").strip()
        session.roles = frozenset(part.strip() for part in form.get("roles", "").split(",") if part.strip())
        session.enigma_status = form.get("enigma_status", "active").strip() or "active"

    def _report(self, session, form, action, outcome, status, code, message) -> str:
        if not session.organisation_id.strip():
            return "The audit log was not written: an audit row needs an organisation id."
        try:
            self.office.audit.append(
                organisation_id=session.organisation_id,
                occurred_at=_instant(form),
                event_type="STAFF_UI_REPORTED",
                category="operational",
                enigma_person_id=session.person_id or None,
                payload={
                    "action": action,
                    "outcome": outcome,
                    "status": status,
                    "code": code,
                    "message": message,
                    "roles": sorted(session.roles),
                },
            )
        except RegulatoryError as exc:
            return f"The audit log refused the outcome: {exc}"
        return "The outcome was written to the audit log."


def build_app() -> StaffApp:
    audit = AuditLog()
    office = StaffOffice(audit=audit)
    access = SessionAccess()
    campaigns = CollectionCampaigns(Ledger(), access, audit=audit)
    return StaffApp(office, campaigns, access)


def make_server(app: StaffApp, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._go("GET")

        def do_POST(self) -> None:
            self._go("POST")

        def _go(self, method: str) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            form = {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}
            split = urlsplit(self.path)
            query = {key: values[-1] for key, values in parse_qs(split.query, keep_blank_values=True).items()}
            cookies = _cookies(self.headers.get("Cookie", ""))
            token = cookies.get("staff_session", "")
            fresh = token not in app.sessions
            if fresh:
                token = secrets.token_urlsafe(18)
                app.sessions[token] = Session()
            page = app.handle(app.sessions[token], method, split.path, form, query)
            body = page.body.encode("utf-8")
            self.send_response(page.status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if fresh:
                self.send_header("Set-Cookie", f"staff_session={token}; HttpOnly; Path=/; SameSite=Lax")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def serve(app: StaffApp, host: str, port: int) -> None:
    httpd = make_server(app, host, port)
    print(f"Staff screens at http://{host}:{port}/staff/", flush=True)
    httpd.serve_forever()


def _headers(session: Session) -> dict:
    return {
        "X-Enigma-Person-Id": session.person_id,
        "X-Enigma-Organisation-Id": session.organisation_id,
        "X-Enigma-Roles": ",".join(sorted(session.roles)),
        "X-Enigma-Status": session.enigma_status or "active",
    }


def _segment(value: str) -> str | None:
    if not value or value.strip() != value or "/" in value:
        return None
    return value


def _cents(raw: str):
    text = raw.strip()
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    return text


def _campaign_body(form: dict) -> dict:
    product = form.get("product_id", "").strip()
    trigger = form.get("fall_away_trigger", "").strip()
    return {
        "recognised_at": form.get("recognised_at", ""),
        "product_id": product or None,
        "start_date": form.get("start_date", "").strip(),
        "end_date": form.get("end_date", "").strip(),
        "base_rate": form.get("base_rate", "").strip(),
        "discount_rate": form.get("discount_rate", "").strip(),
        "fall_away_choice": form.get("fall_away_choice", "").strip(),
        "fall_away_trigger": trigger or None,
        "initiation_fee_discount_cents": _cents(form.get("initiation_fee_discount_cents", "")),
        "service_fee_discount_cents": _cents(form.get("service_fee_discount_cents", "")),
    }


def _election_body(form: dict) -> dict:
    body: dict = {"recognised_at": form.get("recognised_at", "")}
    for name in (
        "vat_on_rand_maxima",
        "late_disbursement",
        "partial_prepayment",
        "interest_on_deferred_initiation",
        "repo_rate_fall",
        "in_duplum_trigger",
        "campaign_fall_away_choice",
        "campaign_fall_away_trigger",
    ):
        value = form.get(name, "").strip()
        if value:
            body[name] = value
    residual = form.get("residual_write_off_threshold_cents", "").strip()
    if residual:
        body["residual_write_off_threshold_cents"] = _cents(residual)
    return body


def _compliance_body(form: dict) -> dict:
    body = {"recognised_at": form.get("recognised_at", "")}
    for name in (
        "legal_name",
        "ncr_registration_number",
        "trading_name",
        "physical_address",
        "postal_address",
        "telephone",
        "bank_name",
        "bank_account_number",
        "branch_code",
        "payment_reference",
    ):
        body[name] = form.get(name, "").strip()
    return body


def _optional_scope(form: dict, name: str):
    raw = form.get(name, "").strip()
    return raw or None


def _collection_body(form: dict, organisation_id: str) -> dict:
    fees: dict = {}
    for fee in FEE_TYPES:
        raw = form.get(f"fee_{fee}", "").strip()
        if raw == "":
            continue
        fees[fee] = _cents(raw)
    end = form.get("end_date", "").strip()
    return {
        "organisation_id": organisation_id,
        "recognised_at": form.get("recognised_at", ""),
        "start_date": form.get("start_date", "").strip(),
        "end_date": end or None,
        "rate_reduction": form.get("rate_reduction", "").strip(),
        "rate_scope": _optional_scope(form, "rate_scope"),
        "fee_reductions": fees,
        "fee_scope": _optional_scope(form, "fee_scope"),
        "payment_holiday": form.get("payment_holiday", "") in {"true", "on", "1"},
        "notice_date": form.get("notice_date", "").strip(),
    }


def _apply_body(form: dict) -> dict:
    selector = form.get("selector", "").strip()
    body: dict = {"recognised_at": form.get("recognised_at", ""), "selector": selector}
    if selector == "product":
        body["product_code"] = form.get("product_code", "").strip()
    elif selector == "loans":
        raw = form.get("loan_ids", "")
        body["loan_ids"] = [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
    return body


def _collection_values(campaign) -> dict:
    return {
        "start_date": campaign.start_date.isoformat(),
        "end_date": "" if campaign.end_date is None else campaign.end_date.isoformat(),
        "rate_reduction": format(campaign.rate_reduction, "f"),
        "rate_scope": campaign.rate_scope or "",
        "notice_date": campaign.notice_date.isoformat(),
        "payment_holiday": campaign.payment_holiday,
        "fee_reductions": dict(campaign.fee_reductions),
        "fee_scope": campaign.fee_scope or "",
    }


def _split_batch(rows: list) -> tuple[list, list]:
    succeeded = []
    failed = []
    for row in rows:
        event = str(row.get("event_type") or "")
        if "BATCH" not in event:
            continue
        if "FAIL" in event:
            failed.append(row)
        elif "SUCCESS" in event:
            succeeded.append(row)
    return succeeded, failed


def _rand_clause(cents: object) -> str:
    shown = render._rands(cents)
    if not shown:
        return ""
    return f" ({shown} rand)"


def _instant(form: dict | None) -> datetime:
    raw = "" if not form else form.get("recognised_at", "")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.tzinfo is not None:
        return parsed
    return datetime.now(JOHANNESBURG)


def _cookies(header: str) -> dict[str, str]:
    found = {}
    for part in header.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        found[key.strip()] = value.strip()
    return found
