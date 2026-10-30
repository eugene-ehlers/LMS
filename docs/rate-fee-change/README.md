# Rate or fee change

A non-campaign change under section 104. It can reduce or zero a rate or a fee, or change the frequency or time for payment of a credit fee or charge. It does not change the contractual term or the contractual instalment. That change is a restructure and is refused.

A collection campaign and an early settlement are out of scope.

The notice document is not produced here. It is generated outside the LMS or by a later document layer. The LMS stores the section 104(2) notice date. A missing notice date, or fewer than five business days before the effective date, fails closed and stores nothing.

Amounts are integer cents. A rate is a periodic decimal, not a cent amount. The recognition date is 00:00 Africa/Johannesburg.

The original contractual rate and fees stay on the loan and are copied for disclosure. Accrual uses the new values from the effective date. When an end date is set, the original rate and fees resume on the next recognition date.

Staff action: `lms.rate_fee_change.write`. Enigma grants it. The LMS does not store the role.

| Topic | Document |
| --- | --- |
| Routes | [routes.md](routes.md) |
| Stored shape | [schema.md](schema.md) |
| Points not settled by the locks | [gaps.md](gaps.md) |
