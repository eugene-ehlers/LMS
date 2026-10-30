# Stored shape

Migration `db/migrations/0008_rate_fee_change.sql` matches the in-process store. Amounts are integer cents. Rates are `numeric(12, 8)`. Dates are Johannesburg recognition dates.

| Store | What it keeps |
| --- | --- |
| `rate_fee_change` | Notice date, effective date, optional end date, new periodic rate, fee payment frequency and time, the actor, and `notice_business_days` fixed at 5 |
| `rate_fee_change_fee` | New fee cents by type |
| `rate_fee_change_account` | Contractual periodic rate, base rate, discount rate, contractual end, and payment frequency copied at apply |
| `rate_fee_change_fee_original` | Contractual fee cents copied at apply |
| `rate_fee_change_instalment` | Copy of the contractual principal lines |

Applying a change does not update `loan_account` or `schedule_line`. The periodic rate and fee amounts on the change are a concession. They apply only through the end date. After that date the concession is zero and the copied contractual rate and fees apply. The loan's contractual rate, fees, and instalment are not written.

The audit event is `RATE_FEE_CHANGE`, category `operational`. The payload carries the outcome, the reason code on failure, the actor, the recognition date, the loan ids, and the before and after values. It does not carry `amount_cents`.
