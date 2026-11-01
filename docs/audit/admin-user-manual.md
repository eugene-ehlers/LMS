# Admin user manual

How an administrator stores the provider choices the LMS is allowed to keep. Mandate strings are the role names the routes already check (`docs/layer2/routes.md`; `docs/staff-ui/README.md`). This manual does not add a role.

Open `/staff/`, submit the session (see `docs/audit/staff-user-manual.md`), and include the role named for the change. A missing role is HTTP 403. Timeout and an ambiguous Enigma status are HTTP 503 (`docs/LOCKED_DECISIONS.md` §15). A successful write ends on the heading “Confirmed”, with a sentence that the operator can continue, and an audit row (`docs/staff-ui/README.md`; `docs/COMMUNICATION.md` §2; `docs/LOCKED_DECISIONS.md` §23).

Amounts are integer cents. `recognised_at` is an aware timestamp. The recognition date is 00:00 Africa/Johannesburg (`docs/LOCKED_DECISIONS.md` §1).

## Elections

Screen: `GET /staff/elections`, then `POST /staff/elections`.

Route: `PUT /v1/staff/organisations/{organisation_id}/elections`.

Role: `lms.elections.write`.

A product override is `GET/POST /staff/products/{product}/elections`, which calls `PUT /v1/staff/organisations/{organisation_id}/products/{product_id}/elections`. The same role is required. A product value overrides the organisation (`docs/LOCKED_DECISIONS.md` §19; `docs/layer2/election-schema.md`).

**Success.** “The organisation elections were stored. You can continue.” A product save names the product id in that sentence.

A blank select is stored unset. The screen does not call `POST .../elections/resolve` and does not fill a default (`docs/staff-ui/README.md`). Resolve fails closed while a required election is unset at both levels (`docs/layer2/routes.md`).

### Residual write-off threshold

Field: `residual_write_off_threshold_cents`, integer cents, zero or greater.

The current platform value is R100, which is 10 000 cents. An unset organisation value and an unset product value fill R100 when the row is resolved. A stored value, including zero, is kept. The list shows the stored null, so a blank on the form is still visible as unset (`docs/LOCKED_DECISIONS.md` §8 and §19; `docs/layer2/election-schema.md`). The write-off is not automatic (`docs/LOCKED_DECISIONS.md` §8; `docs/ORCHESTRATION.md`, write-off flows).

### In-duplum trigger

Field: `in_duplum_trigger`.

Allowed values: `contractual_breach`, `collections_default`. Booking fails closed when the trigger is unset on both the organisation and the product (`docs/LOCKED_DECISIONS.md` §7 and §19). The column has no default (`db/migrations/0007_collections_elections.sql`).

### VAT election

Field: `vat_on_rand_maxima`.

Allowed values: `exclusive`, `inclusive`. `exclusive` is the NCR default for the rand maxima. There is no silent platform choice on the form: unset fails closed at resolve (`docs/LOCKED_DECISIONS.md` §9 and §19; `docs/layer2/election-schema.md`).

The same screen also stores `late_disbursement`, `partial_prepayment`, `interest_on_deferred_initiation`, `repo_rate_fall`, and the campaign fall-away pair. Those are Decision 19 elections. They are outside the list in the heading of this manual, and the allowed values are in `docs/layer2/election-schema.md`.

## Leniency, full-payment threshold, and day count

These three are required at booking. They are not fields on `/staff/elections`.

| Choice | Column | Allowed value | Rule |
| --- | --- | --- | --- |
| Leniency | `leniency_days` | Integer, zero or greater | Unset fails closed. Calendar days, including weekends and public holidays (`docs/LOCKED_DECISIONS.md` §6; `db/migrations/0002_locked_decisions.sql`) |
| Full-payment threshold | `full_payment_threshold_percent` | Greater than 0 and at most 100 | Unset fails closed (`docs/LOCKED_DECISIONS.md` §6) |
| Day count | `day_count_code` | `actual_actual` or `thirty_360` | The credit provider chooses. Accrual is daily (`docs/LOCKED_DECISIONS.md` §5; `db/migrations/0003_elections.sql`) |

The columns sit on `lms.cfg_organisation_settings`, with an optional override on `lms.cfg_product_terms`. The book form at `POST /exercise/book` supplies them for the agreement. A blank is `election-unset` and stores nothing (`docs/demo/demo-script.md`; `docs/audit/staff-user-manual.md`). The booked values are copied onto `lms.election_snapshot`, where null is not a stored election (`db/migrations/0004_ledger_accounts.sql`).

The demo leaves the organisation-settings table empty and sends the elections on the book form (`docs/demo/demo-script.md`).

## Brand header and footer

Screen: `POST /exercise/brand` on the “Brand asset” form (`src/lms/runtime.py`; `docs/demo/demo-script.md`, moment 3).

Fields: organisation id, asset name, and body. The demo asset names are `statement-header` and `statement-footer`.

**Success.** Heading “Brand asset stored”. The list includes `object_key` `brand/{organisation_id}/statement-header` or `brand/{organisation_id}/statement-footer`. The body is the text that was submitted. The object stays in the process store (`docs/demo/demo-script.md`).

An empty body, or an asset name that cannot be used in the key, is `brand-unset` and stores nothing.

`lms.cfg_brand` is the table for display name, support contacts, logo key, and statement footer (`db/migrations/0001_lms_owned.sql`). The statements design copies the logo key onto a stored statement and does not paint the other brand columns as the provider’s legal name (`docs/statements/layer1-design.md`). Legal name, NCR number, addresses, telephone, and payment details come from the compliance row (`docs/LOCKED_DECISIONS.md` §12 and §21).

Decision 23 requires a signed-in person with the correct role before a brand change. `docs/layer2/routes.md` does not name a brand role. The exercise form does not check one of the mandate strings below. This manual does not invent `lms.brand.write`.

## NCR number and provider details

Screen: `GET /staff/compliance`, then `POST /staff/compliance`.

Route: `PUT /v1/staff/organisations/{organisation_id}/compliance`, which calls `ComplianceStore.put` (`docs/layer2/routes.md`).

Role: `lms.compliance.write`.

The row is `lms.cfg_provider_compliance`. Enigma does not hold or return these fields (`docs/LOCKED_DECISIONS.md` §15 and §21).

| Field | What the screen requires |
| --- | --- |
| `legal_name` | Required |
| `ncr_registration_number` | Compulsory. A number of all zeros, including `0000000000`, `0000000`, and `NCRCP0000`, is accepted. A blank is refused |
| `trading_name` | Present. An empty string is allowed |
| `physical_address`, `postal_address`, `telephone` | Required |
| `bank_name`, `bank_account_number`, `branch_code`, `payment_reference` | Required. These are the payment-account details |

**Success.** “Compliance details were stored for {organisation id}. The NCR registration number is {number}. You can continue.” The audit event is `COMPLIANCE_CHANGED` (`docs/layer2/routes.md`).

**Fail closed.** A missing row on GET opens an empty form and shows `compliance-missing`. A blank required field is refused by the store. A blank NCR number is the route message `ncr_registration_number is required` (`docs/staff-ui/README.md`). A statement is not stored without the compliance row (`docs/demo/demo-script.md`).

The comment on `lms.cfg_organisation_settings` that says the NCR number is read from Enigma is not the rule. The conflict is recorded in `docs/statements/implementation-note.md`. Decision 21 is the rule.

## Mandate strings

| Change | Role the route checks |
| --- | --- |
| Elections, including residual, in-duplum trigger, and VAT | `lms.elections.write` |
| Compliance, including the NCR number and provider details | `lms.compliance.write` |
| Campaign create, edit, and end | `lms.campaign.write` |
| Solution-wide operational ceiling | `lms.ceiling.platform.write` |
| Company operational ceiling | `lms.ceiling.company.write` |
| Collection campaign | `lms.collection_campaign.write` |

The audit read accepts any one of the five Layer 2 write roles. It does not accept `lms.collection_campaign.write` on its own. Decision 23 does not name a separate audit role (`docs/layer2/routes.md`; `docs/staff-ui/README.md`).
