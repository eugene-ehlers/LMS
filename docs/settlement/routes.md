# Early settlement routes

Quote, then a receipt that matches the quote. Amounts are integer cents. The value date of a recognised event is 00:00 Africa/Johannesburg.

`docs/LOCKED_DECISIONS.md` was not edited. Gaps are F1 to F7 and S2 in `docs/OPEN_ISSUES.md`.

## Quote

`POST /v1/agreements/{agreement_id}/settlement-quotes`

Modules, in order:

1. `Ledger.quote_settlement`
2. `Documents.settlement_quote`

The ledger method delegates to the calculation engine. It does not keep a second formula. The route refuses the quote when the two totals or the two valid-until dates differ. The quote does not post.

The body is:

| Field | Rule |
|-------|------|
| `as_of` | ISO date. Interest runs through this date. |
| `delivered_on` | ISO date. The quote cannot be delivered before `as_of`. |
| `request_on` | ISO date. Section 113 delivery count starts here. |
| `recognised_at` | Timezone-aware ISO timestamp. |
| `holidays` | List of ISO dates. An omitted or null list fails closed. An empty list means the caller asserts there are none. |
| `interest_cap_present` | `true` or `false`. `false` fails closed. |
| `vat_rate` | Decimal string such as `0.15`. A float is rejected. Omitted fails closed. |
| `repos` | Optional. A non-empty list is rejected. See F5. |

Success is HTTP 200:

```json
{
  "success": true,
  "confirmation": "Settlement quote issued. Amount owing is 133667 cents, valid until 2026-04-17. NCR number NCRCP999.",
  "quote_id": "<uuid>",
  "agreement_id": "<uuid>",
  "amount_owing_cents": 133667,
  "valid_until": "2026-04-17",
  "ncr_registration_number": "NCRCP999",
  "early_termination_cents": 0
}
```

`valid_until` is five business days after delivery. The delivery day is a valid payment date. Weekends and the caller-supplied holidays are not business days. Day-1 early termination is 0 cents.

The NCR number is read from the LMS compliance store. It is not read from Enigma. A short-term or unsecured agreement with no compliance row, or a blank NCR number, fails with `ncr-missing`. Other classifications fail with `quote-classification` before that read. Decision 21 exempts pure hosting and Laybye/BNPL. This route does not invent a settlement formula for them.

The same agreement, `as_of`, and `delivered_on` return the same `quote_id`.

## Execute

`POST /v1/agreements/{agreement_id}/settlements`

Header `Idempotency-Key` is required. The same key and the same body return the stored confirmation and do not post again. The same key with a different body is HTTP 409.

This is not the ordinary receipt flow. A short receipt, a surplus, or a receipt outside the window is not allocated, and it is not posted as an ordinary payment.

Modules, in order:

1. `Ledger.accrue_day` for each day from disbursement through the quote `as_of` date
2. `Ledger.bill_interest`, then `Ledger.levy_service_fee`, on each month-end in that span and on `as_of`
3. `Ledger.post_settlement`

The capitalisation is proved on a copy of the ledger first. The agreement is touched only when that copy reaches 0 cents.

The body is:

| Field | Rule |
|-------|------|
| `quote_id` | The id returned by the quote route. |
| `cents` | Integer. A string or a boolean is rejected. It must equal `amount_owing_cents`. |
| `recognised_at` | Timezone-aware ISO timestamp. The value date must fall on or between `delivered_on` and `valid_until`. |
| `interest_cap_present` | Must be `true`. |
| `vat_rate` | Decimal string, as on the quote. |
| `repos` | Optional list of `{effective_from, annual_rate}`. `annual_rate` is a decimal string. |

Interest stays at the quoted `as_of` amount. A later receipt inside the window does not accrue the days in between. See F2.

The service fee in the settlement month is the full monthly fee. The opening month uses the locked fraction (disbursement through the day before the first due date, over the days in the disbursement month, capped at one fee). A settlement inside the opening month does not shorten that fraction.

`Ledger.post_settlement` allocates in section 126 order: interest, then fees, then principal, including principal that is not yet due. That principal is section 125, not the section 13 prepayment election. A surplus is not sent to a Laybye. See F3.

Success is HTTP 200:

```json
{
  "success": true,
  "confirmation": "Agreement settled. Receipt of 133667 cents allocated in section 126 order. Balance is 0 cents.",
  "agreement_id": "<uuid>",
  "quote_id": "<uuid>",
  "amount_cents": 133667,
  "balance_cents": 0,
  "ncr_registration_number": "NCRCP999"
}
```

The agreement status becomes `settled` only when the balance is 0 cents. The audit log then records `SETTLEMENT_APPLIED` (financial, with `amount_cents`) and `AGREEMENT_STATUS_CHANGED` with status `settled`.

Journals posted by this path use 00:00 Africa/Johannesburg on the value date, including a receipt that was recognised later the same day.

## Failure

A failure is HTTP 422 unless the table says otherwise. The body is:

```json
{"success": false, "code": "quote-mismatch", "reason": "<specific reason>"}
```

| Code | When |
|------|------|
| `timestamp-naive` | `recognised_at` has no timezone. Not audited. |
| `not-found` | Unknown agreement id. HTTP 404. Not audited. |
| `ncr-missing` | No compliance row, or a blank NCR number, on a short-term or unsecured agreement. |
| `election-unset` | A required election is missing. The reason names it, for example `missing election: in_duplum_trigger`. |
| `interest-cap-missing` | `interest_cap_present` is not true. Reason: `no interest cap covers the value date`. |
| `vat-rate-unset` | No VAT rate was supplied. |
| `holidays-unset` | No holiday set was supplied. |
| `repo-quote-unset` | The quote body included repo rows. |
| `quote-window` | The receipt value date is outside delivery and valid-until. |
| `quote-mismatch` | The cents do not equal the quote, or the capitalised ledger does not equal the quote. A booked initiation that differs from the statutory figure is named in cents. Nothing is allocated. |
| `idempotency-required` | The execute header is missing. |
| `idempotency-conflict` | The key was used for a different receipt. HTTP 409. |

After an agreement has been loaded, a failure is written as `SETTLEMENT_REJECTED` with the actor's organisation, the timestamp, the code, and the reason. A success quote is `SETTLEMENT_QUOTED`.
