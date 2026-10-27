# LMS

Post-origination loan management for a South African white-label LMaaS. Enigma owns identity, organisations, memberships, enrolment, roles, and mandates. This repository owns product configuration, statutory reference data, and the financial and operational audit log.

[docs/LOCKED_DECISIONS.md](docs/LOCKED_DECISIONS.md) is the source of truth for calculation, ledger, servicing, and configuration behaviour. Do not invent a default for a choice that document leaves open. The table shapes and the calculation-engine read path are in [docs/lms-owned-configuration.md](docs/lms-owned-configuration.md). The implementation checklist is [docs/IMPLEMENTATION_CHECKLIST.md](docs/IMPLEMENTATION_CHECKLIST.md). Where the design note or the code differs from the locked decisions, the locked decisions win.

## Layout

| Path | What it is |
| --- | --- |
| `db/migrations/0001_lms_owned.sql` | Aurora PostgreSQL schema. Apply as the migration role, with `TimeZone=UTC` |
| `db/migrations/0002_locked_decisions.sql` | Leniency, full-payment threshold, campaign base and discount, and the other stored choices in the locked decisions |
| `db/seed/001_reference.sql` | Gazette figures, the adopted interpretation set, and public holidays for 2026–2032 |
| `src/lms_config` | Ceiling arithmetic and the engine read contract. One implementation, so the formula is not copied into SQL |
| `scripts/render_holidays.py` | Regenerates the holiday block in the seed from the Public Holidays Act rules |
| `docs/IMPLEMENTATION_CHECKLIST.md` | Data structures, draft signatures, invariants, and technical gaps. Not production code |

Day-1 products are Micro/short-term, Unsecured personal, zero-cost BNPL, a CPA lay-by of goods, and a short-term loan with a linked lay-by. The linked lay-by is one loan with the parent, not a secured-loan classification.

## Tests

```bash
python3 -m pytest tests -q
```

The tests are the worked examples in the design note. A change to a gazetted figure or to an adopted reading has to change both.

## Apply

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/0001_lms_owned.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/0002_locked_decisions.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/seed/001_reference.sql
```

PostgreSQL 16. The runtime role is `lms_app`, and each request sets `lms.organisation_id` to the Enigma organisation id. Reference data is not tenant scoped. The runtime role cannot write it.
