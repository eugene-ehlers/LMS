# LMS

Locked rules: [docs/LOCKED_DECISIONS.md](docs/LOCKED_DECISIONS.md) (28 October 2026).

The ledger and account model is `src/lms/ledger/` and `db/migrations/0004_ledger_accounts.sql`. It calls the calculation engine in `src/lms/calc/` and the configuration layer in `src/lms_config/`.

- [docs/account-balance-transaction-model.md](docs/account-balance-transaction-model.md) cites each locked section.
- [docs/ledger-implementation-note.md](docs/ledger-implementation-note.md) lists the tables, the signatures, the calls, the gaps, and the test result.
