# LMS

Post-origination loan management for a South African white-label LMaaS. Enigma owns identity, organisations, memberships, enrolment, roles, and mandates. This repository owns product configuration, statutory reference data, and the financial and operational audit log.

The design, the table shapes, the calculation-engine read path, and the unsettled NCA readings are in [docs/lms-owned-configuration.md](docs/lms-owned-configuration.md).

## Layout

| Path | What it is |
| --- | --- |
| `db/migrations/0001_lms_owned.sql` | Aurora PostgreSQL schema. Apply as the migration role, with `TimeZone=UTC` |
| `db/seed/001_reference.sql` | Gazette figures, the adopted interpretation set, and public holidays for 2026–2032 |
| `src/lms_config` | Ceiling arithmetic and the engine read contract. One implementation, so the formula is not copied into SQL |
| `scripts/render_holidays.py` | Regenerates the holiday block in the seed from the Public Holidays Act rules |

Day-1 products are Micro/short-term, Unsecured personal, zero-cost BNPL, a CPA lay-by of goods, and a short-term loan secured by a zero-interest deposit.

## Tests

```bash
python3 -m pytest tests -q
```

The tests are the worked examples in the design note. A change to a gazetted figure or to an adopted reading has to change both.

## Apply

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/0001_lms_owned.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/seed/001_reference.sql
```

PostgreSQL 16. The runtime role is `lms_app`, and each request sets `lms.organisation_id` to the Enigma organisation id. Reference data is not tenant scoped. The runtime role cannot write it.
