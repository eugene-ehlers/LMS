# Routes

No session middleware. The notice document is not produced by these routes.

A body that carries `contractual_end`, `instalment_cents`, `term`, `term_months`, `schedule`, or `payment_frequency` is refused (`restructure`). The loan's contractual payment frequency is not a field of this change.

A body that carries `payment_holiday`, `campaign_id`, `rate_reduction`, `fee_reductions`, `settlement`, `early_settlement`, or `quote_settlement` is refused (`out-of-scope`).

`recognised_at` must carry a zone. The recognition date is 00:00 Africa/Johannesburg on that calendar day, including a UTC instant that is already the next Johannesburg date. A clock time in a date field is refused.

Fees are integer cents. A float is refused (`fee-cents`). A periodic rate is a decimal string. A float rate is refused (`rate`).

## Apply

```
POST /v1/organisations/{organisation_id}/rate-fee-changes
X-Actor-Id: {staff person id}
```

```json
{
  "recognised_at": "2026-03-02T08:00:00+02:00",
  "notice_date": "2026-03-02",
  "effective_date": "2026-03-09",
  "end_date": null,
  "periodic_rate": "0",
  "fees_cents": {"service": 0},
  "fee_payment_frequency": null,
  "fee_payment_time": null,
  "selector": "loans",
  "loan_ids": ["{loan uuid}"],
  "contractual_fees_cents": {
    "{loan uuid}": {"service": 6000}
  }
}
```

`selector` is one of:

| Value | Body | Selection |
| --- | --- | --- |
| `organisation` | no `loan_ids` | Every loan account in that organisation |
| `loans` | `loan_ids` | Those ledger loan ids, all in that organisation |

`product` is refused (`product-unsupported`). The ledger does not store a product code.

`notice_date` is required. Null or omitted is `notice-missing`. `effective_date` must be on or after the fifth business day after `notice_date` (`lms_config.calendar.add_business_days`, section 2(5)). The notice date is excluded and the fifth business day is included. A shorter gap is `notice-short`. Saturday, Sunday, and the statutory public holidays are not business days. `notice_business_days` is not an election. A value other than 5 is `notice-days`.

`end_date` null keeps the new values until staff set an end date. When it is set, the new values apply on that date. The original rate and fees resume on the next recognition date. See [gaps.md](gaps.md) for that inclusive reading.

`periodic_rate`, when sent, must be strictly below the contractual periodic rate on the effective date and must not be negative. A higher rate is `rate-increase` (section 104(1)). The same rate is `rate-not-reduced`. Zero is allowed.

`fees_cents` is the new ex-VAT amount by fee type: `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`. Each new amount must be strictly below the contractual cents supplied for that loan. The ledger does not store those contractual amounts, so `contractual_fees_cents` is required for every selected loan when a fee changes. A missing original is `fee-not-stored`.

`fee_payment_frequency` is a locked frequency (`weekly`, `fortnightly`, `monthly`, `quarterly`, `bi_annual`, `annual`). It needs `fee_payment_time`, the first Johannesburg date the fee is due, on or after the effective date. The loan schedule is not rewritten.

At least one of a lower rate, a lower fee, or a payment-time change is required. Otherwise the result is `no-change`.

An empty selection is `no-accounts`. An unknown loan fails the whole request (`loan-unknown`) and stores nothing. Two changes that cover the same loan on the same recognition date are `change-overlap`. No precedence is locked.

A day that already has an interest accrual inside the window is `accrual-already-posted`. A fee already levied in the window is `fee-already-levied`. Posted rows are not restated.

Enigma timeout, an ambiguous status, or a suspended enrolment fails closed and stores nothing.

Success is HTTP 200:

```json
{
  "outcome": "success",
  "code": "applied",
  "confirmation": "Rate or fee change {id} applies to 1 account from 2026-03-09 at 00:00 Africa/Johannesburg. ...",
  "change_id": "{uuid}",
  "loan_ids": ["{loan uuid}"]
}
```

Failure is HTTP 422, or 503 when Enigma does not answer, with `outcome` `failure`, a `code`, and a `message` that says what to correct. The same outcome is written to the audit log as `RATE_FEE_CHANGE`.

## End

```
POST /v1/organisations/{organisation_id}/rate-fee-changes/{change_id}/end
X-Actor-Id: {staff person id}
```

```json
{
  "recognised_at": "2026-04-01T08:00:00+02:00",
  "end_date": "2026-03-31"
}
```

This sets the last recognition date of the new values. It does not take a second notice date. Moving the end date later is `end-extends`, because that would apply the reduced values on more days and this command carries no section 104(2) notice. Moving it earlier is allowed when no accrual or levy has already been posted after the new end date.

## Accrual and levy

```
POST /v1/organisations/{organisation_id}/loans/{loan_id}/rate-fee-accruals
```

```json
{
  "recognised_at": "2026-03-09T08:00:00+02:00",
  "interest_cap_present": true
}
```

On a covered day the ledger posts with `periodic_rate_override`. Day count, interest base, and VAT are unchanged. A stored rate above that day's contractual rate is `rate-increase` and is not posted. Zero is a normal rate.

Outside the window the contractual rate is used, including after the end date.

```
POST /v1/organisations/{organisation_id}/loans/{loan_id}/rate-fee-service-fees
```

```json
{
  "recognised_at": "2026-03-09T08:00:00+02:00",
  "monthly_cents": 6000,
  "due_on": "2026-03-09",
  "interest_cap_present": true,
  "vat_rate": "0.15"
}
```

`monthly_cents` is the contractual ex-VAT amount. It must match the cents stored at apply. The route levies the new amount. `Ledger.levy_service_fee` still prices VAT and the monthly cap.

```
POST /v1/organisations/{organisation_id}/loans/{loan_id}/rate-fee-charges
```

Same shape, with `bucket` and `cents` instead of `monthly_cents`. The service fee uses the service-fee route.

If a payment-time overlay is in force, `due_on` must be a date on that overlay. Any other date is `payment-time` and nothing is posted.

A refused accrual or levy is audited. A posted accrual is the ledger transaction. The apply row already records the before and after values.

## Status

```
POST /v1/organisations/{organisation_id}/rate-fee-changes/status
```

```json
{"on": "2026-03-09", "loan_id": "{loan uuid}"}
```

```
POST /v1/organisations/{organisation_id}/loans/{loan_id}/rate-fee-change-status
```

`on` is the last Johannesburg date to include. The response is the query result. `outcome` inside it is the last audited success or failure for that selection. The query does not write a new audit row.
