# Data dictionary

Tables that hold the agreement, the money, the statement, the provider, and the audit trail. Column lists follow `db/migrations/`. Money is integer cents (`bigint`). The recognition date is 00:00 Africa/Johannesburg (`docs/LOCKED_DECISIONS.md` §1). A naive timestamp has no Johannesburg day and is refused.

The behavioural tests drive an in-memory store. PostgreSQL enforces the migrations. There is no repository between them (`docs/ledger-implementation-note.md`). `organisation_id` is `text` on the loan and the ledger, and `uuid` on the configuration and audit tables. That difference is unresolved (`db/migrations/0004_ledger_accounts.sql`).

There is no `lms.agreement` table. The agreement row is `lms.loan_account`.

## Agreements and frozen identity

`lms.loan_account` (`db/migrations/0004_ledger_accounts.sql`). One row per loan or Laybye hold. The hold is `instrument_kind` `laybye_hold` and points at its parent. Identity is frozen at booking (`docs/LOCKED_DECISIONS.md` §4 and §16).

| Column | Meaning |
| --- | --- |
| `organisation_id`, `person_id` | Opaque Enigma ids (`docs/LOCKED_DECISIONS.md` §15) |
| `loan_id` | Ledger id. The human loan number is issued by the LMS and linked to the application number (`docs/LOCKED_DECISIONS.md` §25). It is not a column on this table |
| `frozen_full_name`, `frozen_id_number`, `frozen_service_address` | The three frozen identity fields. Each is required and must not be blank |
| `instrument_kind` | `loan` or `laybye_hold` |
| `classification`, `payment_frequency` | Product class and one of the six frequencies (`docs/LOCKED_DECISIONS.md` §14) |
| `disbursement_value_date`, `quoted_disbursement`, `contractual_end` | Civil dates |
| `cash_advanced_cents`, `capitalised_initiation_cents` | Integer cents |

`lms.election_snapshot` copies the booked elections for that loan. Null is not stored. Day count may be null only for a zero-price product. Columns include `leniency_days`, `full_payment_threshold_percent`, `day_count_code`, `vat_on_rand_maxima`, `base_rate`, and `discount_rate`.

`lms.schedule_version` and `lms.schedule_line` hold the contractual schedule. `principal_cents` on a line is integer cents. `due_on` is a civil date.

## Balances and journals

Balances are the sum of `lms.ledger_entry`. They are not a second stored balance, except the statement snapshot below. `laybye_hold` is credit-normal. The other buckets are debit-normal (`docs/LOCKED_DECISIONS.md` §1 and §8).

`lms.ledger_transaction`

| Column | Meaning |
| --- | --- |
| `kind` | The journal kind (accrual, fee, payment, reversal, and the other posted kinds) |
| `value_date` | Johannesburg civil date of the event |
| `recognised_at` | Aware timestamp. Decision 1 treats the value date as 00:00 that day |
| `recognition_sequence` | Order of acceptance inside the organisation. Callers do not choose it (`docs/LOCKED_DECISIONS.md` §1) |
| `amount_cents`, `memo_rands` | Posted cents, and the unbilled memo where the journal keeps one |
| `reverses_transaction_id` | A reversal is a new transaction. The value date stays the original date |
| `attributed_due_on` | The due date the receipt counts toward (`docs/LOCKED_DECISIONS.md` §6) |

`lms.ledger_entry`: `debit_cents` and `credit_cents` are integer cents. One side is zero. `bucket` is `principal`, `interest`, `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`, or `laybye_hold`.

`lms.ledger_sequence` stores the last ledger sequence for the organisation. `lms.default_episode` stores `ceiling_cents` and `accrued_cents` for an in-duplum episode (`docs/LOCKED_DECISIONS.md` §7). `lms.service_fee_levy` allows one parent service fee in a calendar month (`docs/LOCKED_DECISIONS.md` §4).

## Statements

`lms.client_statement`: `organisation_id`, `person_id`, `statement_id`, `period_start`, `period_end`. One row per client, organisation, and period (`docs/LOCKED_DECISIONS.md` §12).

`lms.client_statement_balance`: `loan_id`, `bucket`, `opening_cents`, `closing_cents`. Each loan keeps its own opening and closing so section 109 still holds (`docs/LOCKED_DECISIONS.md` §12).

## Compliance and brand

`lms.cfg_provider_compliance` (`db/migrations/0005_statement_compliance.sql`): `legal_name`, `ncr_registration_number`, `trading_name`, `physical_address`, `postal_address`, `telephone`, `bank_name`, `bank_account_number`, `branch_code`, `payment_reference`. A blank required column fails closed. Trading name may be an empty string. These columns are LMS configuration (`docs/LOCKED_DECISIONS.md` §15 and §21).

`lms.cfg_brand` (`db/migrations/0001_lms_owned.sql`): `organisation_id`, `brand_code`, `display_name`, `support_phone`, `support_email`, `logo_object_key`, `statement_footer`. Presentation only. The calculation engine does not read it. The demo header and footer objects are `brand/{organisation_id}/statement-header` and `brand/{organisation_id}/statement-footer` (`docs/demo/demo-script.md`).

`lms.cfg_organisation_settings` holds timezone `Africa/Johannesburg`, currency `ZAR`, and the election columns added in `0002_locked_decisions.sql`, `0003_elections.sql`, and `0007_collections_elections.sql` (`leniency_days`, `full_payment_threshold_percent`, `day_count_code`, `vat_on_rand_maxima`, `in_duplum_trigger`, and the other Decision 19 fields). Product overrides are on `lms.cfg_product_terms`.

## Audit events

`lms.audit_event` (`db/migrations/0001_lms_owned.sql`, sequence added in `0003_elections.sql`):

| Column | Meaning |
| --- | --- |
| `occurred_at`, `event_id` | When the event was sealed, and its id |
| `organisation_id` | Tenant. Opaque organisation id |
| `enigma_person_id`, `actor_kind`, `actor_enigma_id` | Who did it, from Enigma (`docs/LOCKED_DECISIONS.md` §23) |
| `event_type` | Code in `lms.ref_audit_event_type` |
| `amount_cents` | Integer cents on a financial event. An operational event leaves it null |
| `previous_hash`, `row_hash` | The chain. SHA-256 over the canonical row (`db/migrations/0003_elections.sql`) |
| `recognition_sequence` | Assigned by `lms.seal_audit_event`. Callers cannot choose it (`docs/IMPLEMENTATION_NOTE.md`) |
| `payload` | JSON object. Staff before/after values for a configuration change (`docs/layer2/routes.md`) |

`lms.audit_chain_head` stores `last_event_id`, `last_occurred_at`, `last_hash`, and `last_sequence` for the organisation. `lms.audit_idempotency` stores one row per organisation and idempotency key.

The table comment excludes credentials and consumer identity numbers from the audit row. The three frozen identity fields live on `lms.loan_account`, not in this chain (`docs/LOCKED_DECISIONS.md` §16 and §23).
