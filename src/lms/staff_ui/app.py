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
from lms.collections.authority import RandCeiling as AuthorityCeiling
from lms.collections.errors import CollectionsError
from lms.collections.service import WRITE_OFF_ACTION, Collections
from lms.ledger.service import Ledger
from lms.regulatory.audit import AuditLog
from lms.regulatory.errors import RegulatoryError
from lms.servicing.errors import ServicingError
from lms.servicing.service import Servicing, displayed_loan_number
from lms.staff.api import dispatch as staff_dispatch
from lms.staff.ceilings import COMPANY, PLATFORM, RandCeiling, tighter
from lms.staff.errors import StaffError
from lms.staff.service import StaffOffice
from lms.staff_ui.access import SessionAccess
from lms.staff_ui import render
from lms.statements.service import Documents
from lms_config.brand import BrandChrome, BrandDirectory, BrandReadError
from lms_config.calendar import value_date, value_instant

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
    def __init__(
        self,
        office: StaffOffice,
        campaigns: CollectionCampaigns,
        access: SessionAccess,
        *,
        servicing: Servicing | None = None,
        collections: Collections | None = None,
        documents: Documents | None = None,
        brand: BrandDirectory | None = None,
    ) -> None:
        self.office = office
        self.campaigns = campaigns
        self.access = access
        self.servicing = servicing or Servicing(audit=office.audit)
        self.collections = collections or Collections(self.servicing)
        self.documents = documents or Documents(self.servicing, office.compliance)
        self.brand = brand if brand is not None else BrandDirectory()
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
        if parts == ["staff", "collections"] and method == "GET":
            return self._view(session, "Collections", render.collections_form())
        if parts == ["staff", "collections"] and method == "POST":
            return self._collections_view(session, form)
        if parts == ["staff", "collections", "write-off"] and method == "POST":
            return self._collections_write_off(session, form)
        if parts == ["staff", "statements"] and method == "GET":
            return self._view(session, "Statements", render.statement_lookup_form())
        if parts == ["staff", "statements"] and method == "POST":
            return self._statements_find(session, form)
        if parts == ["self", "register"] and method in {"GET", "POST"}:
            return self._enigma_page(session, method, form, "register")
        if parts == ["self", "sign-on"] and method in {"GET", "POST"}:
            return self._enigma_page(session, method, form, "sign-on")
        if parts == ["self", "statement"] and method == "GET":
            return self._self_statement(session)
        if parts == ["self", "settlement-quote"] and method == "GET":
            return self._self_quote(session)
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
        inner = render.election_reading(payload, "inherits") + render.election_form(
            f"/staff/products/{product_id}/elections",
            payload,
            heading=f"Product {product_id}",
            blank="inherits",
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
        platform_status, platform_payload = self._staff(session, "GET", "/v1/staff/ceilings/platform", {})
        org = _segment(session.organisation_id)
        if org is None:
            company_status, company_payload = 422, {
                "code": "organisation-unset",
                "message": "The Enigma organisation id is missing or contains a slash, so the company ceiling route cannot be addressed.",
            }
        else:
            company_status, company_payload = self._staff(
                session, "GET", f"/v1/staff/organisations/{org}/ceilings", {},
            )
        if scope == "platform":
            status, payload = platform_status, platform_payload
            action = "/staff/ceilings/platform"
            title = "Solution-wide ceiling"
            check = False
        else:
            status, payload = company_status, company_payload
            action = "/staff/ceilings/company"
            title = "Company ceiling"
            check = True
        if status != 200:
            return self._route_fail(session, {}, "ceiling-list", status, payload, action)
        if platform_status == 200 and company_status == 200:
            lines = _tighter_lines(platform_payload.get("ceilings") or [], company_payload.get("ceilings") or [])
            note = ""
        elif scope == "platform":
            lines = []
            note = (
                "The company ceiling was not read, so the tighter limit is not shown. "
                + str(company_payload.get("message") or "")
            )
        else:
            lines = []
            note = (
                "The platform ceiling was not read, so the tighter limit is not shown. "
                + str(platform_payload.get("message") or "")
            )
        return self._view(
            session, title,
            render.ceiling_page(
                scope=title,
                action=action,
                rows=payload.get("ceilings") or [],
                check=check,
                tighter=lines,
                tighter_note=note,
            ),
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

    def _collections_view(self, session: Session, form: dict) -> Page:
        agreement_id = form.get("agreement_id", "").strip()
        recognised = _recognition(form)
        if _segment(agreement_id) is None:
            return self._fail(
                session, form, action="collections-view", status=422, code="agreement-unset",
                message="An agreement id is required, and it cannot contain a slash.",
                return_to="/staff/collections",
            )
        if recognised is None:
            return self._fail(
                session, form, action="collections-view", status=422, code="recognised-at",
                message="recognised_at must be a timezone-aware timestamp. The recognition date is 00:00 Africa/Johannesburg.",
                return_to="/staff/collections",
            )
        if not self._own_agreement(session, agreement_id):
            return self._fail(
                session, form, action="collections-view", status=404, code="not-found",
                message="No agreement with that id is held for this organisation.",
                return_to="/staff/collections",
            )
        try:
            view = self.collections.view(agreement_id, recognised)
        except CollectionsError as exc:
            return self._fail(
                session, form, action="collections-view", status=exc.status, code=exc.code,
                message=str(exc), return_to="/staff/collections",
            )
        payload = {
            "agreement_id": view.agreement_id,
            "recognition": recognised.isoformat(),
            "contractual_breaches": [day.isoformat() for day in view.contractual_breaches],
            "collections_default": view.collections_default,
            "open_episode_ceiling": view.open_episode_ceiling,
            "provision_cents": view.provision_cents,
            "residual_threshold_cents": view.residual_threshold_cents,
        }
        return self._view(session, "Collections", render.collections_result(payload))

    def _collections_write_off(self, session: Session, form: dict) -> Page:
        agreement_id = form.get("agreement_id", "").strip()
        return_to = "/staff/collections"
        if _segment(agreement_id) is None:
            return self._fail(
                session, form, action="write-off", status=422, code="agreement-unset",
                message="An agreement id is required, and it cannot contain a slash.",
                return_to=return_to,
            )
        recognised = _recognition(form)
        if recognised is None:
            return self._fail(
                session, form, action="write-off", status=422, code="recognised-at",
                message="recognised_at must be a timezone-aware timestamp. The recognition date is 00:00 Africa/Johannesburg.",
                return_to=return_to,
            )
        amount = _integer_cents(form.get("amount_cents", ""))
        if amount is None:
            return self._fail(
                session, form, action="write-off", status=422, code="amount-cents",
                message="amount_cents must be integer cents.",
                return_to=return_to,
            )
        if not self._own_agreement(session, agreement_id):
            return self._fail(
                session, form, action="write-off", status=404, code="not-found",
                message="No agreement with that id is held for this organisation.",
                return_to=return_to,
            )
        self.access.current = session
        try:
            try:
                self.access.check(session.organisation_id, session.person_id, WRITE_OFF_ACTION)
            except ServicingError as exc:
                return self._fail(
                    session, form, action="write-off", status=exc.status, code=exc.code,
                    message=str(exc), return_to=return_to,
                )
            try:
                self._allocate_unapplied(agreement_id)
            except ServicingError as exc:
                return self._fail(
                    session, form, action="write-off", status=exc.status, code=exc.code,
                    message=str(exc), return_to=return_to,
                )
            try:
                company_row = self.office.ceilings.company(session.organisation_id, WRITE_OFF_ACTION)
            except StaffError as exc:
                return self._fail(
                    session, form, action="write-off", status=exc.status, code=exc.code,
                    message=str(exc), return_to=return_to,
                )
            platform_row = self.office.ceilings.platform(WRITE_OFF_ACTION)
            platform = None if platform_row is None else AuthorityCeiling(
                platform_row.amount_cents, version=platform_row.version,
            )
            company = None if company_row is None else AuthorityCeiling(
                company_row.amount_cents, version=company_row.version,
            )
            try:
                view = self.collections.write_off(
                    agreement_id,
                    recognised_at=recognised,
                    actor_id=session.person_id,
                    amount_cents=amount,
                    platform=platform,
                    company=company,
                    mandate_allowed=True,
                    access=self.access,
                )
            except CollectionsError as exc:
                return self._fail(
                    session, form, action="write-off", status=exc.status, code=exc.code,
                    message=str(exc), return_to=return_to,
                )
        finally:
            self.access.current = None
        summary = (
            f"Agreement {view.agreement_id} was written off. "
            f"Recognition date is {recognised.isoformat()}. You can continue."
        )
        return self._ok(
            session, form, "write-off",
            {
                "agreement_id": view.agreement_id,
                "written_off": view.written_off,
                "amount_cents": amount,
                "recognition": recognised.isoformat(),
            },
            summary,
            "/staff/collections",
        )

    def _allocate_unapplied(self, agreement_id: str) -> None:
        pending = [
            payment
            for payment in self.servicing.payments.values()
            if payment.status == "unapplied" and payment.agreement_id == agreement_id
        ]
        pending.sort(key=lambda payment: (payment.recognised_at, payment.payment_id))
        for payment in pending:
            self.servicing.apply_payment(
                payment.payment_id,
                agreement_id=agreement_id,
                attributed_due_on=payment.attributed_due_on,
            )

    def _statements_find(self, session: Session, form: dict) -> Page:
        needle = form.get("loan_or_id", "").strip()
        if not needle:
            return self._fail(
                session, form, action="statement-find", status=422, code="lookup-unset",
                message="A loan number or ID number is required.",
                return_to="/staff/statements",
            )
        if not session.organisation_id.strip():
            return self._fail(
                session, form, action="statement-find", status=422, code="organisation-unset",
                message="The Enigma organisation id is missing, so stored statements cannot be located.",
                return_to="/staff/statements",
            )
        matched = [
            record
            for record in self.servicing.agreements.values()
            if record.organisation_id == session.organisation_id
            and _agreement_matches(record, needle)
        ]
        if any(not record.loan_number.strip() for record in matched):
            return self._fail(
                session, form, action="statement-find", status=422, code="loan-number-missing",
                message="The agreement has no loan number, so the stored statement is not shown.",
                return_to="/staff/statements",
            )
        loan_numbers = _numbers_for(matched)
        rows = []
        for statement in self.documents.statements.values():
            if statement.organisation_id != session.organisation_id:
                continue
            payload = _statement_payload(statement, loan_numbers)
            payload["loans"] = [
                loan for loan in payload["loans"] if loan["loan_id"] in loan_numbers
            ]
            if payload["loans"]:
                rows.append(payload)
        inner = render.statement_lookup_form() + render.stored_statements(
            rows,
            empty="No stored statement matches that loan number or ID number.",
        )
        return self._view(session, "Statements", inner)

    def _enigma_page(self, session: Session, method: str, form: dict, kind: str) -> Page:
        if method == "POST":
            return self._fail(
                session, form, action=kind, status=422, code="enigma-redirect",
                message="Registration and sign-on are Enigma. This screen does not accept those details.",
                return_to=f"/self/{kind}",
            )
        title = "Registration" if kind == "register" else "Sign on"
        return self._view(session, title, render.enigma_redirect(kind))

    def _self_statement(self, session: Session) -> Page:
        refused = self._consumer_gate(session, "self-statement", "/self/statement")
        if refused is not None:
            return refused
        loan_numbers = self._loan_numbers(session.organisation_id, session.person_id)
        rows = [
            _statement_payload(statement, loan_numbers)
            for statement in self.documents.statements.values()
            if statement.organisation_id == session.organisation_id
            and statement.person_id == session.person_id
        ]
        return self._view(
            session,
            "Stored statement",
            render.stored_statements(rows, empty="No stored statement is held for this consumer."),
        )

    def _self_quote(self, session: Session) -> Page:
        refused = self._consumer_gate(session, "self-quote", "/self/settlement-quote")
        if refused is not None:
            return refused
        rows = [
            _quote_payload(quote)
            for quote in self.documents.quotes.values()
            if quote.organisation_id == session.organisation_id and quote.person_id == session.person_id
        ]
        return self._view(
            session,
            "Settlement quote",
            render.stored_quotes(rows, empty="No stored settlement quote is held for this consumer."),
        )

    def _consumer_gate(self, session: Session, action: str, return_to: str) -> Page | None:
        if session.enigma_status == "timeout":
            return self._fail(
                session, {}, action=action, status=503, code="enigma-timeout",
                message="LOCKED_DECISIONS §15: Enigma timed out. The statement and the quote stay unopened.",
                return_to=return_to,
            )
        if session.enigma_status == "suspended":
            return self._fail(
                session, {}, action=action, status=403, code="enigma-suspended",
                message="LOCKED_DECISIONS §15: the enrolment is suspended. The statement and the quote stay unopened.",
                return_to=return_to,
            )
        if session.enigma_status != "active" or not session.person_id.strip() or not session.organisation_id.strip():
            return self._fail(
                session, {}, action=action, status=403, code="enigma-sign-on",
                message="A consumer sees a stored statement or settlement quote only after Enigma sign-on. This screen does not issue either.",
                return_to=return_to,
            )
        return None

    def _own_agreement(self, session: Session, agreement_id: str) -> bool:
        record = self.servicing.agreements.get(agreement_id)
        return record is not None and record.organisation_id == session.organisation_id

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
        try:
            brand = self.brand.presentation(session.organisation_id)
        except BrandReadError:
            brand = BrandChrome("unread")
        return Page(status, render.document(title, session, inner, show_nav=show_nav, brand=brand))

    def _loan_numbers(self, organisation_id: str, person_id: str | None = None) -> dict[str, str]:
        numbers: dict[str, str] = {}
        for record in self.servicing.agreements.values():
            if record.organisation_id != organisation_id:
                continue
            if person_id is not None and record.person_id != person_id:
                continue
            if record.ledger_loan_id:
                numbers[record.ledger_loan_id] = displayed_loan_number(record.loan_number, laybye=False)
            if record.laybye_loan_id:
                numbers[record.laybye_loan_id] = displayed_loan_number(record.loan_number, laybye=True)
        return numbers

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
    servicing = Servicing(audit=audit)
    return StaffApp(
        office,
        campaigns,
        access,
        servicing=servicing,
        collections=Collections(servicing),
        documents=Documents(servicing, office.compliance),
    )


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


def _tighter_lines(platform_rows: list, company_rows: list) -> list[dict]:
    by_platform = {row["action"]: row for row in platform_rows}
    by_company = {row["action"]: row for row in company_rows}
    lines = []
    for action in sorted(set(by_platform) | set(by_company)):
        platform = by_platform.get(action)
        company = by_company.get(action)
        if platform is None:
            lines.append({"action": action, "stopped": True})
            continue
        platform_row = RandCeiling(
            PLATFORM, action, int(platform["amount_cents"]), platform["currency"], "", int(platform["version"]),
        )
        company_row = None
        if company is not None:
            company_row = RandCeiling(
                COMPANY,
                action,
                int(company["amount_cents"]),
                company["currency"],
                company["organisation_id"],
                int(company["version"]),
            )
        applied = tighter(action, 0, platform_row, company_row)
        lines.append({
            "action": action,
            "stopped": False,
            "platform_cents": applied.platform_cents,
            "company_cents": applied.company_cents,
            "limit_cents": applied.limit_cents,
        })
    return lines


def _agreement_matches(record, needle: str) -> bool:
    if record.frozen_id_number == needle:
        return True
    core = record.loan_number.strip()
    if not core:
        return False
    return needle == core or needle == displayed_loan_number(core, laybye=True)


def _numbers_for(records) -> dict[str, str]:
    numbers: dict[str, str] = {}
    for record in records:
        if record.ledger_loan_id:
            numbers[record.ledger_loan_id] = displayed_loan_number(record.loan_number, laybye=False)
        if record.laybye_loan_id:
            numbers[record.laybye_loan_id] = displayed_loan_number(record.loan_number, laybye=True)
    return numbers


def _statement_payload(statement, loan_numbers: dict[str, str] | None = None) -> dict:
    numbers = loan_numbers or {}
    return {
        "statement_id": statement.statement_id,
        "period_start": statement.period_start.isoformat(),
        "period_end": statement.period_end.isoformat(),
        "loans": [
            {
                "loan_id": loan.loan_id,
                "loan_number": numbers.get(loan.loan_id, ""),
                "frozen_id_number": loan.frozen_id_number,
                "principal_debt_cents": loan.principal_debt_cents,
                "payments_received_cents": loan.payments_received_cents,
                "interest_billed_cents": loan.interest_billed_cents,
                "fees_levied_cents": loan.fees_levied_cents,
                "insurance_levied_cents": loan.insurance_levied_cents,
                "collection_levied_cents": loan.collection_levied_cents,
                "default_administration_levied_cents": loan.default_administration_levied_cents,
                "opening": dict(loan.opening),
                "closing": dict(loan.closing),
            }
            for loan in statement.loans
        ],
    }


def _quote_payload(quote) -> dict:
    return {
        "agreement_id": quote.agreement_id,
        "as_of": quote.as_of.isoformat(),
        "delivered_on": quote.delivered_on.isoformat(),
        "valid_until": quote.valid_until.isoformat(),
        "principal_cents": quote.principal_cents,
        "interest_cents": quote.interest_cents,
        "fee_cents": quote.fee_cents,
        "early_termination_cents": quote.early_termination_cents,
        "total_cents": quote.total_cents,
        "components": list(quote.components),
    }


def _integer_cents(raw: str) -> int | None:
    text = raw.strip()
    if text.isdigit():
        return int(text)
    return None


def _recognition(form: dict | None) -> datetime | None:
    raw = "" if not form else form.get("recognised_at", "")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return value_instant(value_date(parsed))


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
