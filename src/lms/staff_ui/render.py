"""HTML for the staff screens. Values are escaped. No business rules."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Mapping
from zoneinfo import ZoneInfo

from lms.collection_campaigns.models import FEE_TYPES, SCOPES, ROLE as COLLECTION_ROLE
from lms.staff.authority import (
    ROLE_CAMPAIGN_WRITE,
    ROLE_CEILING_COMPANY_WRITE,
    ROLE_CEILING_PLATFORM_WRITE,
    ROLE_COMPLIANCE_WRITE,
    ROLE_ELECTIONS_WRITE,
)
from lms.staff.campaigns import (
    DOES_NOT_FALL_AWAY,
    FALLS_AWAY_ON_DEFAULT,
    FALL_AWAY_TRIGGERS,
)
from lms_config.locked import (
    INTEREST_ON_INITIATION_NONE,
    INTEREST_ON_INITIATION_PERMITTED,
    LATE_DISBURSEMENT_ADJUST,
    LATE_DISBURSEMENT_KEEP,
    PREPAY_DROP,
    PREPAY_SHORTEN,
    REPO_FALL_CONTRACT,
    REPO_FALL_LOWER,
    TRIGGER_COLLECTIONS_DEFAULT,
    TRIGGER_CONTRACTUAL_BREACH,
    VAT_EXCLUSIVE,
    VAT_INCLUSIVE,
)

JOHANNESBURG = ZoneInfo("Africa/Johannesburg")

ROLES = (
    ROLE_CAMPAIGN_WRITE,
    ROLE_ELECTIONS_WRITE,
    ROLE_COMPLIANCE_WRITE,
    ROLE_CEILING_PLATFORM_WRITE,
    ROLE_CEILING_COMPANY_WRITE,
    COLLECTION_ROLE,
)

ELECTION_CHOICES = {
    "vat_on_rand_maxima": (VAT_EXCLUSIVE, VAT_INCLUSIVE),
    "late_disbursement": (LATE_DISBURSEMENT_ADJUST, LATE_DISBURSEMENT_KEEP),
    "partial_prepayment": (PREPAY_SHORTEN, PREPAY_DROP),
    "interest_on_deferred_initiation": (
        INTEREST_ON_INITIATION_NONE,
        INTEREST_ON_INITIATION_PERMITTED,
    ),
    "repo_rate_fall": (REPO_FALL_CONTRACT, REPO_FALL_LOWER),
    "in_duplum_trigger": (TRIGGER_CONTRACTUAL_BREACH, TRIGGER_COLLECTIONS_DEFAULT),
    "campaign_fall_away_choice": (FALLS_AWAY_ON_DEFAULT, DOES_NOT_FALL_AWAY),
    "campaign_fall_away_trigger": tuple(sorted(FALL_AWAY_TRIGGERS)),
}


def esc(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def now_jhb() -> str:
    return datetime.now(JOHANNESBURG).isoformat(timespec="seconds")


def document(title: str, session, inner: str, *, show_nav: bool) -> str:
    nav = _nav() if show_nav else ""
    who = "No Enigma session"
    if session.person_id or session.organisation_id:
        who = f"{session.person_id} at {session.organisation_id}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
body {{ font: 16px/1.45 system-ui, sans-serif; margin: 1.25rem; max-width: 54rem; color: #1c1917; }}
nav a {{ margin-right: 0.75rem; }}
label {{ display: block; margin: 0.55rem 0; }}
input, select, textarea {{ font: inherit; width: min(36rem, 100%); }}
button, a.continue {{ font: inherit; }}
.panel {{ border: 1px solid #d6d3d1; padding: 1rem; margin: 1rem 0; }}
.success {{ border-color: #166534; background: #f0fdf4; }}
.failure {{ border-color: #991b1b; background: #fef2f2; }}
.note {{ color: #44403c; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #e7e5e4; text-align: left; padding: 0.35rem 0.4rem; vertical-align: top; }}
</style>
</head>
<body>
<header>
<p>LMS staff · {esc(who)}</p>
{nav}
</header>
<main>
{inner}
</main>
</body>
</html>
"""


def _nav() -> str:
    links = (
        ("/staff/", "Home"),
        ("/staff/campaigns", "Campaigns"),
        ("/staff/elections", "Elections"),
        ("/staff/compliance", "Compliance"),
        ("/staff/ceilings/platform", "Solution ceiling"),
        ("/staff/ceilings/company", "Company ceiling"),
        ("/staff/collection-campaigns", "Collection campaigns"),
        ("/staff/batch", "Batch status"),
    )
    return "<nav>" + "".join(f'<a href="{esc(href)}">{esc(label)}</a>' for href, label in links) + "</nav>"


def home(session) -> str:
    roles = ", ".join(sorted(session.roles)) if session.roles else ""
    role_list = "".join(f"<li><code>{esc(role)}</code></li>" for role in ROLES)
    return f"""
<h1>Staff session</h1>
<p>Enigma holds identity and access. This screen keeps the opaque person id, organisation id, and role names Enigma already returned. It does not register a consumer and it does not collect an email address or a password.</p>
<p>The route names are the ones the existing commands already check.</p>
<ul>{role_list}</ul>
<form method="post" action="/staff/session">
<label>Person id <input name="person_id" value="{esc(session.person_id)}" autocomplete="off" required></label>
<label>Organisation id <input name="organisation_id" value="{esc(session.organisation_id)}" autocomplete="off" required></label>
<label>Roles, comma-separated <input name="roles" value="{esc(roles)}" autocomplete="off"></label>
<label>Enigma status
<select name="enigma_status">
<option value="active" {"selected" if session.enigma_status == "active" else ""}>active</option>
<option value="timeout" {"selected" if session.enigma_status == "timeout" else ""}>timeout</option>
<option value="ambiguous" {"selected" if session.enigma_status == "ambiguous" else ""}>ambiguous</option>
<option value="suspended" {"selected" if session.enigma_status == "suspended" else ""}>suspended</option>
</select>
</label>
<button type="submit">Use this Enigma session</button>
</form>
"""


def success(summary: str, payload: Mapping, continue_href: str, audit_note: str) -> str:
    return f"""
<section class="panel success" data-outcome="success">
<h1>Confirmed</h1>
<p>{esc(summary)}</p>
{_facts(payload)}
<p>{esc(audit_note)}</p>
<p><a class="continue" href="{esc(continue_href)}">Continue</a></p>
</section>
"""


def failure(pending, audit_note: str) -> str:
    return f"""
<section class="panel failure" data-outcome="failure">
<h1>This step did not succeed</h1>
<p>Reason: {esc(pending.message)}</p>
<p>Code: {esc(pending.code)}. Status: {esc(pending.status)}.</p>
<p>Nothing further on this step will run until you acknowledge this failure.</p>
<p>{esc(audit_note)}</p>
<form method="post" action="/staff/acknowledge">
<input type="hidden" name="nonce" value="{esc(pending.nonce)}">
<button type="submit">Acknowledge the failure</button>
</form>
</section>
"""


def acknowledged(pending) -> str:
    return f"""
<section class="panel" data-outcome="acknowledged">
<h1>Failure acknowledged</h1>
<p>You acknowledged this failure: {esc(pending.message)}</p>
<p>The step was not applied. You can return to the form and correct it.</p>
<p><a href="{esc(pending.return_to)}">Return to the form</a></p>
</section>
"""


def session_saved() -> str:
    return """
<section class="panel success" data-outcome="success">
<h1>Enigma session held</h1>
<p>The opaque ids and role names are held in this browser. No LMS record was written. You can continue.</p>
<p><a class="continue" href="/staff/">Continue</a></p>
</section>
"""


def campaign_list(rows: list) -> str:
    body = "".join(
        "<tr>"
        f"<td><a href=\"/staff/campaigns/{esc(row.get('campaign_id'))}\">{esc(row.get('campaign_id'))}</a></td>"
        f"<td>{esc(row.get('product_id') or 'organisation')}</td>"
        f"<td>{esc(row.get('start_date'))}</td>"
        f"<td>{esc(row.get('end_date'))}</td>"
        f"<td>{esc(row.get('base_rate'))}</td>"
        f"<td>{esc(row.get('discount_rate'))}</td>"
        f"<td>{esc(row.get('net_rate'))}</td>"
        f"<td>{esc(row.get('version'))}</td>"
        "</tr>"
        for row in rows
    )
    if not body:
        body = "<tr><td colspan=\"8\">No campaigns are stored for this organisation.</td></tr>"
    return f"""
<h1>Campaigns</h1>
<p><a href="/staff/campaigns/new">Create a campaign</a></p>
<table>
<thead><tr><th>Campaign</th><th>Product</th><th>Start</th><th>End</th><th>Base</th><th>Discount</th><th>Net</th><th>Version</th></tr></thead>
<tbody>{body}</tbody>
</table>
"""


def campaign_form(action: str, values: Mapping | None, *, heading: str) -> str:
    values = values or {}
    trigger = values.get("fall_away_trigger") or ""
    product = values.get("product_id") or ""
    return f"""
<h1>{esc(heading)}</h1>
<p class="note">Rates are decimal strings. 0.05 is 5 %. Amounts are integer cents. The net rate is returned by the route.</p>
<form method="post" action="{esc(action)}">
{_hidden_time()}
<label>Product id <input name="product_id" value="{esc(product)}"> <span class="note">Blank stores an organisation campaign.</span></label>
<label>Start date <input name="start_date" value="{esc(values.get('start_date', ''))}" required></label>
<label>End date <input name="end_date" value="{esc(values.get('end_date', ''))}" required></label>
<label>Base rate <input name="base_rate" value="{esc(values.get('base_rate', ''))}" required></label>
<label>Discount rate <input name="discount_rate" value="{esc(values.get('discount_rate', ''))}" required></label>
<label>Fall-away choice
<select name="fall_away_choice">
<option value="">Choose</option>
<option value="{esc(FALLS_AWAY_ON_DEFAULT)}" {"selected" if values.get("fall_away_choice") == FALLS_AWAY_ON_DEFAULT else ""}>{esc(FALLS_AWAY_ON_DEFAULT)}</option>
<option value="{esc(DOES_NOT_FALL_AWAY)}" {"selected" if values.get("fall_away_choice") == DOES_NOT_FALL_AWAY else ""}>{esc(DOES_NOT_FALL_AWAY)}</option>
</select>
</label>
<label>Fall-away trigger
<select name="fall_away_trigger">
<option value="">None</option>
{_options(tuple(sorted(FALL_AWAY_TRIGGERS)), trigger)}
</select>
</label>
<label>Initiation fee discount (cents) <input name="initiation_fee_discount_cents" value="{esc(values.get('initiation_fee_discount_cents', 0))}" required></label>
<label>Service fee discount (cents) <input name="service_fee_discount_cents" value="{esc(values.get('service_fee_discount_cents', 0))}" required></label>
<button type="submit">Save campaign</button>
</form>
"""


def campaign_end_form(campaign_id: str) -> str:
    return f"""
<h2>End this campaign</h2>
<p class="note">The route sets the end date from the recognition timestamp. Booked agreements are not repriced by that route.</p>
<form method="post" action="/staff/campaigns/{esc(campaign_id)}/end">
{_hidden_time()}
<button type="submit">End campaign</button>
</form>
"""


def election_list(organisation: Mapping, products: list) -> str:
    rows = "".join(
        "<tr>"
        f"<td><a href=\"/staff/products/{esc(row.get('product_id'))}/elections\">{esc(row.get('product_id'))}</a></td>"
        f"<td>{_election_brief(row)}</td>"
        "</tr>"
        for row in products
    )
    if not rows:
        rows = "<tr><td colspan=\"2\">No product override is stored.</td></tr>"
    return f"""
<h1>Elections</h1>
<p class="note">A blank field is stored as unset. A product blank inherits when a later resolve runs. This screen does not resolve and does not fill a default.</p>
<h2>Organisation</h2>
{_facts(organisation)}
{election_form("/staff/elections", organisation)}
<h2>Products</h2>
<table><thead><tr><th>Product</th><th>Stored values</th></tr></thead><tbody>{rows}</tbody></table>
<form method="get" action="/staff/products/open">
<label>Open a product <input name="product_id" required></label>
<button type="submit">Open product elections</button>
</form>
"""


def election_form(action: str, values: Mapping | None, *, heading: str = "Edit elections") -> str:
    values = values or {}
    fields = []
    for name, choices in ELECTION_CHOICES.items():
        current = values.get(name) or ""
        fields.append(
            f"<label>{esc(name)} <select name=\"{esc(name)}\">"
            f"<option value=\"\">Unset</option>{_options(choices, current)}</select></label>"
        )
    residual = values.get("residual_write_off_threshold_cents")
    residual_value = "" if residual is None else residual
    fields.append(
        "<label>residual_write_off_threshold_cents "
        f"<input name=\"residual_write_off_threshold_cents\" value=\"{esc(residual_value)}\">"
        " <span class=\"note\">Integer cents. Blank stays unset.</span></label>"
    )
    return f"""
<h2>{esc(heading)}</h2>
<form method="post" action="{esc(action)}">
{_hidden_time()}
{''.join(fields)}
<button type="submit">Save elections</button>
</form>
"""


def compliance_form(values: Mapping | None, notice: str) -> str:
    values = values or {}
    fields = (
        ("legal_name", True),
        ("ncr_registration_number", False),
        ("trading_name", False),
        ("physical_address", True),
        ("postal_address", True),
        ("telephone", True),
        ("bank_name", True),
        ("bank_account_number", True),
        ("branch_code", True),
        ("payment_reference", True),
    )
    controls = []
    for name, required in fields:
        req = " required" if required else ""
        note = ""
        if name == "ncr_registration_number":
            note = " <span class=\"note\">Compulsory. A test number of all zeros is accepted.</span>"
        if name == "trading_name":
            note = " <span class=\"note\">May be empty.</span>"
        controls.append(
            f"<label>{esc(name)} <input name=\"{esc(name)}\" value=\"{esc(values.get(name, ''))}\"{req}>{note}</label>"
        )
    notice_html = f"<p class=\"note\">{esc(notice)}</p>" if notice else ""
    return f"""
<h1>Compliance details</h1>
{notice_html}
<p class="note">These facts are LMS data. Enigma does not supply them. Payment-account details are the bank name, account number, branch code, and payment reference.</p>
<form method="post" action="/staff/compliance">
{_hidden_time()}
{''.join(controls)}
<button type="submit">Save compliance details</button>
</form>
"""


def ceiling_page(*, scope: str, action: str, rows: list, check: bool) -> str:
    body = "".join(
        "<tr>"
        f"<td>{esc(row.get('action'))}</td>"
        f"<td>{esc(row.get('amount_cents'))}</td>"
        f"<td>{esc(_rands(row.get('amount_cents')))}</td>"
        f"<td>{esc(row.get('currency'))}</td>"
        f"<td>{esc(row.get('version'))}</td>"
        "</tr>"
        for row in rows
    )
    if not body:
        body = "<tr><td colspan=\"5\">No ceiling is stored.</td></tr>"
    check_form = ""
    if check:
        check_form = f"""
<h2>Check an amount against the tighter ceiling</h2>
<p class="note">This calls the existing apply route. It does not write a ceiling and it does not post a journal.</p>
<form method="post" action="/staff/ceilings/check">
{_hidden_time()}
<label>Action <input name="action" required></label>
<label>Amount (cents) <input name="amount_cents" required></label>
<label>Organisation id <input name="organisation_id" required></label>
<button type="submit">Check amount</button>
</form>
"""
    return f"""
<h1>{esc(scope)} ceiling</h1>
<p class="note">Amounts are integer cents in ZAR. Zero is a real ceiling. The route applies the tighter of the solution-wide and company amounts when an amount is checked. A missing platform ceiling stops that check.</p>
<table>
<thead><tr><th>Action</th><th>Cents</th><th>Rand</th><th>Currency</th><th>Version</th></tr></thead>
<tbody>{body}</tbody>
</table>
<h2>Set a ceiling</h2>
<form method="post" action="{esc(action)}">
{_hidden_time()}
<label>Action <input name="action" required></label>
<label>Amount (cents) <input name="amount_cents" required></label>
<button type="submit">Save ceiling</button>
</form>
{check_form}
"""


def collection_list(rows: list) -> str:
    body = "".join(
        "<tr>"
        f"<td><a href=\"/staff/collection-campaigns/{esc(row.campaign_id)}\">{esc(row.campaign_id)}</a></td>"
        f"<td>{esc(row.start_date.isoformat())}</td>"
        f"<td>{esc(row.end_date.isoformat() if row.end_date else 'open-ended')}</td>"
        f"<td>{esc(format(row.rate_reduction, 'f'))}</td>"
        f"<td>{esc(row.rate_scope or '')}</td>"
        f"<td>{'yes' if row.payment_holiday else 'no'}</td>"
        f"<td>{esc(row.notice_date.isoformat())}</td>"
        "</tr>"
        for row in rows
    )
    if not body:
        body = "<tr><td colspan=\"7\">No collection campaign is held for this organisation.</td></tr>"
    return f"""
<h1>Collection campaigns</h1>
<p class="note">The collection-campaign route has no list method. This table is the campaigns the service already holds for this organisation. It does not decide which campaign applies, and it does not change a contractual term or instalment.</p>
<p><a href="/staff/collection-campaigns/new">Create a collection campaign</a></p>
<table>
<thead><tr><th>Campaign</th><th>Start</th><th>End</th><th>Rate reduction</th><th>Rate duration</th><th>Payment holiday</th><th>Notice date</th></tr></thead>
<tbody>{body}</tbody>
</table>
"""


def collection_form(action: str, values: Mapping | None, *, heading: str) -> str:
    values = values or {}
    fees = values.get("fee_reductions") or {}
    fee_inputs = []
    for fee in FEE_TYPES:
        current = fees.get(fee, "")
        fee_inputs.append(
            f"<label>{esc(fee)} reduction (cents) <input name=\"fee_{esc(fee)}\" value=\"{esc(current)}\"></label>"
        )
    end = values.get("end_date") or ""
    checked = " checked" if values.get("payment_holiday") else ""
    return f"""
<h1>{esc(heading)}</h1>
<p class="note">A blank end date is sent as open-ended. The route decides whether that is accepted. A rate or fee reduction needs a duration of campaign_period or rest_of_term. A blank duration is not filled in. Notice is the date the section 104(2) notice was given. This screen does not generate the notice.</p>
<form method="post" action="{esc(action)}">
{_hidden_time()}
<label>Start date <input name="start_date" value="{esc(values.get('start_date', ''))}" required></label>
<label>End date <input name="end_date" value="{esc(end)}"> <span class="note">Blank is open-ended.</span></label>
<label>Rate reduction <input name="rate_reduction" value="{esc(values.get('rate_reduction', ''))}" required></label>
<label>Rate duration
<select name="rate_scope">
<option value="">None</option>
{_options(SCOPES, values.get('rate_scope') or '')}
</select>
</label>
<label>Notice date <input name="notice_date" value="{esc(values.get('notice_date', ''))}" required></label>
<label><input type="checkbox" name="payment_holiday" value="true"{checked}> Payment holiday</label>
<fieldset>
<legend>Fee reductions</legend>
{''.join(fee_inputs)}
<label>Fee duration
<select name="fee_scope">
<option value="">None</option>
{_options(SCOPES, values.get('fee_scope') or '')}
</select>
</label>
</fieldset>
<button type="submit">Save collection campaign</button>
</form>
"""


def collection_end_form(campaign_id: str) -> str:
    return f"""
<h2>End this collection campaign</h2>
<form method="post" action="/staff/collection-campaigns/{esc(campaign_id)}/end">
{_hidden_time()}
<label>End date <input name="end_date" required></label>
<button type="submit">End collection campaign</button>
</form>
"""


def collection_apply_form(campaign_id: str) -> str:
    return f"""
<h1>Apply collection campaign</h1>
<p class="note">One selector only. The route refuses a mix of organisation, product, and loan list.</p>
<form method="post" action="/staff/collection-campaigns/{esc(campaign_id)}/apply">
{_hidden_time()}
<label>Selector
<select name="selector">
<option value="organisation">organisation</option>
<option value="product">product</option>
<option value="loans">loans</option>
</select>
</label>
<label>Product code <input name="product_code"></label>
<label>Loan ids <textarea name="loan_ids" rows="4"></textarea></label>
<button type="submit">Apply</button>
</form>
<p><a href="/staff/collection-campaigns/{esc(campaign_id)}">Back to the campaign</a></p>
"""


def batch_status(succeeded: list, failed: list, *, gap: str) -> str:
    return f"""
<h1>Batch status</h1>
<p class="note">{esc(gap)}</p>
<h2>Last successful run</h2>
{_batch_table(succeeded)}
<h2>Last failed run</h2>
{_batch_table(failed)}
<h2>Failure reasons</h2>
{_reasons(failed)}
"""


def plain(title: str, message: str) -> str:
    return f"<h1>{esc(title)}</h1><p>{esc(message)}</p>"


def _batch_table(rows: list) -> str:
    if not rows:
        return "<p>None recorded.</p>"
    body = "".join(
        "<tr>"
        f"<td>{esc(row.get('occurred_at'))}</td>"
        f"<td>{esc(row.get('event_type'))}</td>"
        f"<td>{esc(row.get('enigma_person_id'))}</td>"
        f"<td>{esc(row.get('payload'))}</td>"
        "</tr>"
        for row in rows[-1:]
    )
    return (
        "<table><thead><tr><th>When</th><th>Event</th><th>Actor</th><th>Payload</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _reasons(rows: list) -> str:
    if not rows:
        return "<p>None recorded.</p>"
    items = []
    for row in rows:
        payload = row.get("payload") or {}
        reason = payload.get("reason") or payload.get("message") or payload
        items.append(f"<li>{esc(reason)}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def _facts(payload: Mapping) -> str:
    rows = []
    for key, value in payload.items():
        rows.append(f"<dt>{esc(key)}</dt><dd>{esc(value)}</dd>")
    if not rows:
        return ""
    return "<dl>" + "".join(rows) + "</dl>"


def _options(choices, current: object) -> str:
    return "".join(
        f'<option value="{esc(choice)}" {"selected" if choice == current else ""}>{esc(choice)}</option>'
        for choice in choices
    )


def _election_brief(row: Mapping) -> str:
    parts = [f"{key}={value}" for key, value in row.items() if key != "product_id" and value is not None]
    return esc(", ".join(parts) or "All unset")


def _rands(cents: object) -> str:
    if isinstance(cents, bool) or not isinstance(cents, int):
        return ""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole}.{part:02d}"


def _hidden_time() -> str:
    return f'<label>Recognised at <input name="recognised_at" value="{esc(now_jhb())}" required></label>'
