# Audit and security

Controls an auditor can trace to a locked decision or a design note. This note does not add a control.

## Mandate check before a write

Every staff command carries `X-Enigma-Person-Id`, `X-Enigma-Organisation-Id`, `X-Enigma-Roles`, and `X-Enigma-Status` (`docs/layer2/routes.md`). The command runs only when the status is `active` and the role string for that command is present.

| Write | Mandate string |
| --- | --- |
| Elections | `lms.elections.write` |
| Compliance | `lms.compliance.write` |
| Campaigns | `lms.campaign.write` |
| Solution-wide ceiling | `lms.ceiling.platform.write` |
| Company ceiling | `lms.ceiling.company.write` |
| Collection campaign | `lms.collection_campaign.write` |

The strings are the constants in `src/lms/staff/authority.py` and `src/lms/collection_campaigns/models.py`. Decision 23 requires the role name to be descriptive. The examples in the lock are `lms.elections.write` and `lms.campaign.write`.

A missing role or a suspended enrolment is HTTP 403. The organisation on the path must be the organisation on the session. A mismatch is `mandate-denied` (`docs/layer2/routes.md`). A blank person id fails closed and is not audited as a successful write (`docs/LOCKED_DECISIONS.md` §23).

The audit read accepts any one of the five Layer 2 write roles. Decision 23 does not name a separate audit role, so none was added (`docs/layer2/routes.md`). An operator who holds only `lms.collection_campaign.write` cannot open the batch screen (`docs/staff-ui/README.md`).

A brand object stored at `POST /exercise/brand` does not check one of these strings. Decision 23 still requires a signed-in person with the correct role for a brand change. No brand role is named. See `docs/audit/admin-user-manual.md`.

## Audit hash chain

`lms.seal_audit_event` runs before the row is stored (`db/migrations/0003_elections.sql`; `docs/IMPLEMENTATION_NOTE.md`).

- `recognition_sequence` is the next value for that organisation, taken under the organisation advisory lock. Callers cannot choose it. Same-day events sort by this sequence (`docs/LOCKED_DECISIONS.md` §1).
- `previous_hash` is the `row_hash` of the current `lms.audit_chain_head` for the organisation. The first row in an organisation has no predecessor.
- `row_hash` is SHA-256 of the canonical text. The canonical text includes the sequence and the previous hash.
- `lms.audit_chain_head.last_hash` and `last_sequence` move to the new row in the same seal.

A financial event requires `amount_cents`. An operational event must leave `amount_cents` null. The seal rejects the other combination (`db/migrations/0003_elections.sql`).

Staff configuration writes append an operational row with the Enigma person id, the timestamp, and a payload of before and after (`docs/LOCKED_DECISIONS.md` §23; `docs/layer2/routes.md`). Event types include `ELECTION_CHANGED` and `COMPLIANCE_CHANGED`.

A naive recognition timestamp has no Johannesburg day, so no audit row is written and the failure is returned (`docs/LOCKED_DECISIONS.md` §1 and §2). An unknown agreement id has no organisation to attach, so no audit row is written.

## POPIA and the three frozen identity fields

Decision 23 requires role-based access and an audit record sufficient to show who acted and whether they had the mandate, so the record can be used in a POPIA audit.

The three fields are `frozen_full_name`, `frozen_id_number`, and `frozen_service_address` on `lms.loan_account` (`docs/LOCKED_DECISIONS.md` §16; `db/migrations/0004_ledger_accounts.sql`). They are copied from the Enigma booking read at booking. A later change in Enigma does not rewrite them. The LMS does not keep the consumer’s email or mobile for registration or for collection contact (`docs/LOCKED_DECISIONS.md` §15 and §27).

The audit table comment excludes consumer identity numbers from `lms.audit_event` (`db/migrations/0001_lms_owned.sql`). Staff search returns the frozen identity number only on the stored statement, and only to a caller who already holds a staff write role (`docs/layer2/routes.md`; `docs/LOCKED_DECISIONS.md` §12 and §27).

## Enigma timeout and an ambiguous status

Decision 15: fail closed on timeout, on an ambiguous status, and on a suspended enrolment.

On the staff routes, timeout and ambiguous are HTTP 503. Suspended is HTTP 403. Nothing is written (`docs/layer2/routes.md`). The session form offers those four statuses so the failure can be shown (`docs/staff-ui/README.md`).

On the consumer statement and settlement-quote screens, timeout returns `enigma-timeout` and leaves the statement and the quote unopened. Suspended returns `enigma-suspended`. Any other status, or a blank person or organisation id, returns `enigma-sign-on` (`src/lms/runtime.py`; `docs/LOCKED_DECISIONS.md` §15).

A timeout or an ambiguous response from Enigma, the decision-engine stub, the debit-order stub, or the push provider is reported as a failure. It is not treated as success (`docs/COMMUNICATION.md` §3).
