# Staff screens

These screens call the existing routes. They do not re-implement campaign, election, compliance, ceiling, or collection-campaign rules.

The package is `lms.staff_ui`. `StaffApp.handle` returns an HTML page. `python -m lms.staff_ui` serves it on `127.0.0.1:8765` (`STAFF_UI_HOST` and `STAFF_UI_PORT` override the bind).

`build_app()` shares one `AuditLog` between `StaffOffice` and `CollectionCampaigns`. A command the route accepts is visible to both the domain event the route writes and the `STAFF_UI_REPORTED` row the screen writes.

## Session

`GET /staff/` holds the opaque Enigma person id, organisation id, roles, and Enigma status for this browser session. It is not consumer registration. There is no email or password field.

Staff routes receive `X-Enigma-Person-Id`, `X-Enigma-Organisation-Id`, `X-Enigma-Roles`, and `X-Enigma-Status`. Collection-campaign routes receive `X-Actor-Id`. The session is presented as that actor for the duration of one collection dispatch.

An organisation id or product id that is blank, has surrounding whitespace, or contains `/` is not placed in a path. The screen stops with that reason.

## Status feedback

Every POST that changes data, or that the screen refuses before calling a route, ends in one of two pages:

- Success. The page states what was stored and that the operator can continue. Navigation is hidden. The only next step is the Continue link.
- Failure. The page states the route's code and message (or the screen's specific reason when the route was not called). Navigation is hidden. The operator acknowledges that failure before any other request is accepted. A mismatched acknowledgement nonce leaves the failure in place.

A GET that the route refuses is the same failure page, so the operator acknowledges it before leaving.

Each of those outcomes is appended to the shared audit log as `STAFF_UI_REPORTED` (`category=operational`) with the action, outcome, HTTP status, code, message, roles, and Enigma person id. The timestamp is the form's `recognised_at` when that value is a timezone-aware ISO instant, otherwise the current Africa/Johannesburg time. The domain event (`CAMPAIGN_CREATED`, `ELECTION_CHANGED`, and the rest) is written by the route, not by the screen. A blank organisation id cannot be audited; the page says the audit row was not written.

`STAFF_UI_REPORTED` is not in `ref_audit_event_type`. The in-process log accepts it. See K4 in `docs/OPEN_ISSUES.md`.

## Screens

Roles are the names already used by the routes.

| Screen | Path | Route | Role |
| --- | --- | --- | --- |
| Campaign list | `GET /staff/campaigns` | `GET /v1/staff/organisations/{org}/campaigns` | `lms.campaign.write` |
| Create campaign | `GET /staff/campaigns/new`, `POST /staff/campaigns` | `POST /v1/staff/organisations/{org}/campaigns` | `lms.campaign.write` |
| Edit campaign | `GET/POST /staff/campaigns/{id}` | `GET` and `PATCH /v1/staff/organisations/{org}/campaigns/{id}` | `lms.campaign.write` |
| End campaign | `POST /staff/campaigns/{id}/end` | `POST /v1/staff/organisations/{org}/campaigns/{id}/end` | `lms.campaign.write` |
| Organisation elections | `GET/POST /staff/elections` | `GET` and `PUT /v1/staff/organisations/{org}/elections` | `lms.elections.write` |
| Product elections | `GET/POST /staff/products/{product}/elections` | `GET` and `PUT /v1/staff/organisations/{org}/products/{product}/elections` | `lms.elections.write` |
| Compliance | `GET/POST /staff/compliance` | `GET` and `PUT /v1/staff/organisations/{org}/compliance` | `lms.compliance.write` |
| Platform ceiling | `GET/POST /staff/ceilings/platform` | `GET` and `PUT /v1/staff/ceilings/platform` | `lms.ceiling.platform.write` |
| Company ceiling | `GET/POST /staff/ceilings/company` | `GET` and `PUT /v1/staff/organisations/{org}/ceilings` | `lms.ceiling.company.write` |
| Ceiling check | `POST /staff/ceilings/check` | `POST /v1/staff/ceilings/apply` | `lms.ceiling.company.write` |
| Collection-campaign list | `GET /staff/collection-campaigns` | No list route. See K2. | `lms.collection_campaign.write` |
| Create collection campaign | `GET /staff/collection-campaigns/new`, `POST /staff/collection-campaigns` | `POST /v1/collection-campaigns` | `lms.collection_campaign.write` |
| Edit collection campaign | `GET/POST /staff/collection-campaigns/{id}` | `POST /v1/collection-campaigns/{id}` | `lms.collection_campaign.write` |
| End collection campaign | `POST /staff/collection-campaigns/{id}/end` | `POST /v1/collection-campaigns/{id}/end` | `lms.collection_campaign.write` |
| Apply collection campaign | `GET/POST /staff/collection-campaigns/{id}/apply` | `POST /v1/organisations/{org}/collection-campaigns/{id}/applications` | `lms.collection_campaign.write` |
| Batch status | `GET /staff/batch` | `GET /v1/staff/organisations/{org}/audit` | Any Layer 2 staff write role. See K8. |

The audit extract used by the batch screen accepts any of `lms.campaign.write`, `lms.elections.write`, `lms.compliance.write`, `lms.ceiling.platform.write`, or `lms.ceiling.company.write`. Decision 23 does not name a separate audit role.

### Campaigns

Fields sent to the route: `product_id` (blank is an organisation campaign), `start_date`, `end_date`, `base_rate`, `discount_rate`, `fall_away_choice`, `fall_away_trigger`, `initiation_fee_discount_cents`, `service_fee_discount_cents`, `recognised_at`. The first option of each fall-away select is blank, so the browser does not submit `falls_away_on_default` on its own. Money fields are integer cents. The screen does not submit a net rate and does not call `campaign_rate` or fee preview. The confirmation shows the route's `net_rate` and `version`. Ending a campaign sends `recognised_at`; the route sets the end date.

### Elections

Organisation and product screens edit that level only. A blank optional field is omitted, so the route stores it unset. The screen does not call `POST .../elections/resolve` and does not fill a residual threshold. The residual field is integer cents; blank stays unset.

Fields: `vat_on_rand_maxima`, `late_disbursement`, `partial_prepayment`, `interest_on_deferred_initiation`, `repo_rate_fall`, `in_duplum_trigger`, `residual_write_off_threshold_cents`, `campaign_fall_away_choice`, `campaign_fall_away_trigger`, `recognised_at`.

### Compliance

Fields: `legal_name`, `ncr_registration_number`, `trading_name`, `physical_address`, `postal_address`, `telephone`, `bank_name`, `bank_account_number`, `branch_code`, `payment_reference`, `recognised_at`. The NCR number is marked compulsory. The field is not blocked in the browser, so a blank value reaches the route and the operator sees that route's reason. A number of all zeros, including `0000000` and `NCRCP0000`, is sent as typed and accepted by the route. An empty trading name is sent as an empty string. A missing compliance row on GET (`compliance-missing`) opens an empty form. A blank NCR on save is the route's message `ncr_registration_number is required` (K9).

### Ceilings

The platform and company pages list the stored rows. Amounts are submitted as integer cents. The page also shows the same integer as rand (`10000` cents is `100.00` rand) so the operator can read it. Zero is sent as zero. The company page's check posts `action`, `amount_cents`, and `organisation_id` to `POST /v1/staff/ceilings/apply`. That route reads both ceilings and keeps the lower amount. It does not post a journal and it does not write a ceiling. A missing platform ceiling, and an amount above the tighter ceiling, are shown as the route's refusal. An amount equal to the ceiling is allowed.

### Collection campaigns

Create and edit send `organisation_id`, `recognised_at`, `start_date`, `end_date`, `rate_reduction`, `rate_scope`, `fee_reductions`, `fee_scope`, `payment_holiday`, and `notice_date`. A blank end date is JSON `null` (open-ended). A blank rate or fee scope is omitted, so the route sees no duration. Fee inputs are `fee_initiation`, `fee_service`, `fee_credit_insurance`, `fee_default_administration`, `fee_collection_costs`, and `fee_additional_monthly`; a blank fee is omitted. `payment_holiday` is true when the box is checked.

There is no list or read route (K2). The list and the edit form read `CollectionCampaigns.campaigns` for the signed-in organisation only. They do not apply overlap, notice, or rate rules. The list page says that.

Apply sends only the chosen selector: organisation (no `product_code`, no `loan_ids`), product (`product_code` only), or loans (`loan_ids` only). Extra fields left in the form are not posted.

When the session is active and the person and organisation are present but `lms.collection_campaign.write` is missing, the screen does not call the route. `authorise` would report that as an ambiguous Enigma status (K3). Timeout and a suspended enrolment are still sent to the route.

### Batch status

The screen calls the staff audit extract from `1970-01-01` through `9999-12-31` and shows rows whose `event_type` contains `BATCH`. A type containing `FAIL` is a failed run; a type containing `SUCCESS` is a successful run. No route records those rows (K1). The page states that gap. It does not accrue, capitalise, or flag default. The empty state does not say the operator can continue.

A session that holds only `lms.collection_campaign.write` cannot open this screen, because the audit route does not accept that role (K8).

## Out of scope

These paths explain the refusal and do not call a route. A POST is a held failure the operator must acknowledge.

- `GET/POST /staff/register` — consumer self-service registration. Decision 15 sends the consumer to Enigma.
- `GET/POST /staff/collection-notices` — collection notice generation. Decision 27 leaves notices with the collections software.
- `GET/POST /staff/push` — real push-provider integration.

The older Layer 3 draft (`docs/staff-ui/layer3-draft.md` on `cursor/staff-ui-layer3-408d`) describes promises, contacts, write-off, and statement PDF. Those screens are not in this package.

## Gaps

K1–K9 in `docs/OPEN_ISSUES.md` are the gaps found while wiring these screens. The screen does not invent a batch writer, a collection list route, or a locked role.
