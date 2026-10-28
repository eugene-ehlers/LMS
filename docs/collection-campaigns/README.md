# Collection campaigns

A collection campaign is a temporary overlay on loans that are already booked. It can reduce the rate, reduce one or more fees, or skip an instalment. It does not change the contractual term or the contractual instalment. That change is a restructure and is out of scope.

The implementation calls the Layer 0 ledger and the existing calculators. It does not keep a second interest, day-count, VAT, or in-duplum formula.

Amounts are integer cents. A recognition date is 00:00 Africa/Johannesburg (`lms_config.calendar.value_date` and `value_instant`).

| Topic | Document |
| --- | --- |
| Stored shape | [schema.md](schema.md) |
| Bulk apply | [bulk-apply.md](bulk-apply.md) |
| Accrual and fee override | [accrual-override.md](accrual-override.md) |
| Points not settled by the locks | [gaps.md](gaps.md) |

Staff action: `lms.collection_campaign.write`. Enigma grants it. The LMS does not store the role.
