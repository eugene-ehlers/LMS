# Restructure routes

The surface is `lms.restructure.api.dispatch`. It does not book a new origination, quote an early settlement, apply a collection campaign, or post a settlement re-advance.

Every command carries `recognised_at`. The recognition date is the calendar day in Africa/Johannesburg, stored as 00:00 that day. An instant that is still the previous date in UTC can already be the next Johannesburg date. A naive timestamp fails closed and is not given a recognition date.

Headers on every call:

| Header | Meaning |
| --- | --- |
| `X-Enigma-Person-Id` | Opaque staff person id. Blank fails closed. |
| `X-Enigma-Organisation-Id` | Opaque organisation id. It must match the organisation on the path. |
| `X-Enigma-Roles` | Comma-separated role names returned by Enigma. Stored on the audit row. Decision 23 does not name a restructure role, so this path does not require one. |
| `X-Enigma-Status` | `active`, `timeout`, `ambiguous`, or `suspended`. Anything other than `active` fails closed. |

Timeout and an ambiguous Enigma status are HTTP 503. A suspended enrolment or a missing staff identity is HTTP 403. A missing consent, a missing election, a missing identity field, or a decision-engine rejection is HTTP 422. A decision-engine timeout, ambiguous reply, or unavailable engine is HTTP 503.

Money fields are integer cents. The rate is the integer the decision engine supplied (provisional basis points; the wire format is open point D1).

## Restructure

`POST /v1/organisations/{organisation_id}/agreements/{agreement_id}/restructure`

The agreement must already be held by the LMS with status `active`. This route does not originate it. `RestructureService.hold_agreement` records an agreement the LMS already holds so this path can be exercised. Origination remains the booking path.

| Field | Rule |
| --- | --- |
| `recognised_at` | `YYYY-MM-DD` or a timezone-aware ISO timestamp. Stored as 00:00 Africa/Johannesburg on that Johannesburg calendar day. |
| `client_consent` | Boolean. Missing or null fails closed. `false` fails closed. |
| `consent_date` | `YYYY-MM-DD`. Required when consent is true. Stored as that calendar date. |
| `kind` | Omit or send `restructure`. `early_settlement`, `collection_campaign`, and `settlement_readvance` fail closed and change nothing. |
| `elections` | The Decision 19 row to freeze. A null or omitted required field fails closed. The vocabulary is in [schema.md](schema.md). |
| `identity` | `full_name`, `id_number`, and `service_address`. Each must match the identity already frozen on the original agreement. A difference fails closed. Which source wins is open point D3, and this path does not choose. |

The rate, term, instalment, payment frequency, and application number are not accepted on this body. The decision engine supplies them. Sending any of those fields fails closed and the engine is not called.

The engine is `DecisionEngine.supply`. It receives facts already stored (agreement id, outstanding balance in cents, current term, current instalment, current rate). It returns the new rate, term count, payment frequency, instalment in cents, and application number. The LMS stores that reply. It does not calculate an instalment from the rate and the term.

A reply whose term count and instalment are both unchanged is not stored:

- A payment-frequency change alone fails closed. Whether that change is a restructure is not locked.
- A rate change alone fails closed as a collection campaign.
- No change to the rate, term, or instalment fails closed.

A timeout, an ambiguous reply, or an unavailable engine fails closed. The agreement is left as it was. The failure is audited.

On success the original agreement is marked `restructured`, its outstanding balance becomes 0, and that balance is stored on the new agreement. The new agreement links to the original. Its elections, identity, consent, and contractual instalment are frozen.

Success is HTTP 200:

```json
{
  "outcome": "success",
  "confirmation": "Restructure confirmed. New agreement <id> is linked to original agreement <id>. The original agreement is marked restructured. <balance> cents transferred. Contractual instalment <instalment> cents stored for term <count> <frequency>.",
  "original_agreement_id": "<id>",
  "new_agreement_id": "<id>",
  "transferred_balance_cents": 150000,
  "contractual_instalment_cents": 8000,
  "contractual_periodic_rate_bps": 400,
  "term_count": 18,
  "payment_frequency": "monthly",
  "recognition_date": "2026-10-28",
  "recognised_at": "2026-10-28T00:00:00+02:00",
  "client_consent": true,
  "consent_date": "2026-10-28",
  "application_number": "APP-00000002"
}
```

Failure is a specific `reason`. Examples: `missing client consent`, `missing election: residual_write_off_threshold_cents`, `decision engine timeout`, `agreement is already restructured`.

A second request against an agreement that is already restructured fails. The balance is not transferred again.

## Last status

`GET /v1/organisations/{organisation_id}/agreements/{agreement_id}/restructure`

Returns the latest audited outcome for that agreement, including a new agreement created by the restructure. The row includes the actor, the Johannesburg timestamp, and the outcome.

When nothing has been recorded the response is HTTP 200 with `recorded: false` and the reason `no restructure has been recorded for this agreement`.

## Audit

`GET /v1/organisations/{organisation_id}/restructure/audit`

`GET /v1/organisations/{organisation_id}/agreements/{agreement_id}/restructure/audit`

Rows are append-only. Each row has `actor_person_id`, `occurred_at` (00:00 Africa/Johannesburg), `recognition_date`, `outcome` (`success` or `failure`), `reason` or `confirmation`, `roles`, and a payload. Success uses event type `RESTRUCTURE_CONFIRMED`. Failure uses `RESTRUCTURE_FAILED`.

A naive `recognised_at` is returned as a failure and is not written to this log, because Decision 1 gives that timestamp no Johannesburg day. See [gaps.md](gaps.md).
