# Bulk apply

```
POST /v1/organisations/{organisation_id}/collection-campaigns/{campaign_id}/applications
X-Actor-Id: {staff person id}
```

```json
{
  "recognised_at": "2026-03-09T08:00:00+02:00",
  "selector": "organisation"
}
```

`selector` is one of:

| Value | Body | Selection |
| --- | --- | --- |
| `organisation` | no `product_code`, no `loan_ids` | Every loan registered for that organisation |
| `product` | `product_code` | Registered loans of that product in that organisation |
| `loans` | `loan_ids` | Those ledger loan ids, all in that organisation |

The three selectors are alternatives. Sending more than one fails closed (`selector`). An empty match fails closed (`no-accounts`) and writes no application. An unknown loan in a list fails the whole apply (`loan-unknown`).

`recognised_at` must carry a zone. The recognition date is 00:00 Africa/Johannesburg on that calendar day, including a UTC instant that is already the next Johannesburg date.

## Before apply

Register each loan. The ledger does not store a product code or the contractual fee amounts.

```
POST /v1/organisations/{organisation_id}/loans/{loan_id}/registration
```

```json
{
  "product_code": "micro_short_term",
  "contractual_fees_cents": {"service": 6000}
}
```

`loan_ids` are the ledger loan ids. A separate human loan number is not on the Layer 0 account. See [gaps.md](gaps.md).

## What apply does

For each selected loan it stores the contractual rate, fees, instalment lines, and contractual end. It does not write the loan's schedule, term, base rate, or origination discount.

A payment holiday records a skip for each contractual due date that is on or after the apply recognition date and inside the campaign period. A due date that has already passed is not rewritten.

The same loan cannot take two collection campaigns whose periods overlap, including an open-ended campaign. No precedence is locked, so the apply stops (`campaign-overlap`) and nothing in that request is stored.

The staff actor must hold `lms.collection_campaign.write`. Enigma timeout, an ambiguous status, or a suspended enrolment fails closed and stores nothing.

## Other routes

| Route | Effect |
| --- | --- |
| `POST /v1/collection-campaigns` | Create. `end_date` null is open-ended. |
| `POST /v1/collection-campaigns/{campaign_id}` | Replace the campaign fields. Posted accruals are not reversed. |
| `POST /v1/collection-campaigns/{campaign_id}/end` | Set `end_date`. The campaign applies on that date and not after it. |

A body that carries `contractual_end`, `instalment_cents`, `term`, `term_months`, or `schedule` is refused (`restructure`).

The start date must be at least five business days after `notice_date` (`lms_config.calendar.add_business_days`, section 2(5)). A shorter gap is `notice-short`. The notice document is not generated.
