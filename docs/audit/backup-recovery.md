# Backup and recovery

What is recoverable from the repository, and what is recoverable only from the database. This note does not describe how to deploy a host.

## What is in GitHub

The repository is the source for:

| Artefact | Where it lives |
| --- | --- |
| Application code | `src/lms/` and `src/lms_config/` |
| Migrations | `db/migrations/`, applied in filename order |
| Locked decisions and the standing design notes | `docs/LOCKED_DECISIONS.md`, `docs/ORCHESTRATION.md`, `docs/COMMUNICATION.md`, and the design notes cited by the other audit files |
| Tests | `tests/` |

A clone restores that source. It does not restore tenant rows, journals, or issued statements. Those are database contents.

On `main`, `docs/LOCKED_DECISIONS.md` is a stub that points at a missing file. The restored decision text used by the implementation is the document on the branches that contain sections 1 to 29. An auditor comparing `main` with a feature branch should treat the stub as the gap recorded in `docs/OPEN_ISSUES.md` (K6), not as the rule text.

The staff demo also keeps agreements, receipts, and brand objects in the process. A new process starts the loan-number series again at `000000000001` (`docs/demo/demo-script.md`). That process memory is not in GitHub and not in the database.

## What is in the database

PostgreSQL holds the tenant and the money (`docs/ledger-implementation-note.md`):

| Contents | Tables |
| --- | --- |
| Tenant configuration | `lms.cfg_organisation_settings`, `lms.cfg_product`, `lms.cfg_product_terms`, `lms.cfg_provider_compliance`, `lms.cfg_brand`, `lms.cfg_campaign`, `lms.cfg_rand_ceiling` |
| Agreements and schedules | `lms.loan_account`, `lms.election_snapshot`, `lms.schedule_version`, `lms.schedule_line` |
| Ledger | `lms.ledger_transaction`, `lms.ledger_entry`, `lms.ledger_sequence`, `lms.default_episode`, `lms.service_fee_levy` |
| Statements | `lms.client_statement`, `lms.client_statement_balance` |
| Audit | `lms.audit_event`, `lms.audit_chain_head`, `lms.audit_idempotency` |

Frozen identity is on `lms.loan_account`. Provider disclosure is on `lms.cfg_provider_compliance`. Brand presentation is on `lms.cfg_brand`, and the demo header and footer bytes are object-store keys (`docs/demo/demo-script.md`). A database restore does not, by itself, restore an object that was written only to the process `MemoryStore`.

Reference rows (caps, frequencies, audit event types) are in the `lms.ref_*` tables created by the migrations. They are part of the database, and the migrations that insert them are in GitHub.

## Point-in-time restore

When the database is hosted, recovery to a chosen timestamp is a point-in-time restore of that host. The intended host is Amazon RDS. The restore procedure for that host is not written in this note.

Until a host exists, the recoverable copies are the GitHub commit of the code and migrations, and whatever database backup the operator has taken of the tables above. The in-memory demo is recoverable only by running the staff demo again. That run issues new agreement ids (`docs/demo/demo-script.md`).
