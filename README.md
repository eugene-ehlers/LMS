# LMS

Post-origination loan management for South African credit providers. Read [docs/LOCKED_DECISIONS.md](docs/LOCKED_DECISIONS.md) (28 October 2026) before changing calculation, ledger, servicing, or configuration behaviour. Identity, organisations, and mandates stay in Enigma.

Servicing orchestration is `src/lms/servicing/`. It calls the calculation engine in `src/lms/calc/`, the configuration layer in `src/lms_config/`, and the ledger in `src/lms/ledger/`.

- [docs/servicing/primary-flows.md](docs/servicing/primary-flows.md)
- [docs/servicing/implementation-design.md](docs/servicing/implementation-design.md)
- [docs/servicing/implementation-note.md](docs/servicing/implementation-note.md)
- [docs/account-balance-transaction-model.md](docs/account-balance-transaction-model.md)
- [docs/ledger-implementation-note.md](docs/ledger-implementation-note.md)
- [docs/day1-calc-engine-note.md](docs/day1-calc-engine-note.md)
- [docs/lms-owned-configuration.md](docs/lms-owned-configuration.md)
