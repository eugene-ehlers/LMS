# Decision-engine dummy

The LMS submits an application and stores the approval it receives. It does not re-decide whether a loan is concurrent, subsequent, settled-and-readvanced, or restructured. Those rules stay in the decision engine. This dummy does not implement them, and it does not price.

Call site: `engine.decide(application)`.

| Scenario | Constructor | Result |
| --- | --- | --- |
| Fixed success | `DecisionEngineDummy.fixed_success()` | Approval with the canned figures below |
| Fixed decline | `DecisionEngineDummy.fixed_decline()` | Decline with an application number and no pricing |

The success constructor can fix the short-term flag and the canned figures. The default flag is `five_percent`. Pass `short_term_rate_band=None` when the flag is not applicable, or `three_percent` for the other band. The dummy does not choose the band from the product type or from the requested amount.

## Request

`Application`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `consumer.person_id` | string | yes | Opaque Enigma person id |
| `consumer.name` | string | yes | Provisional. Not a locked field list |
| `consumer.id_number` | string | yes | Provisional |
| `requested_amount_cents` | int | yes | Zero or positive cents |
| `product_type` | string | yes | Accepted and not interpreted. Day-1 examples: `short_term`, `unsecured_personal` |
| `term_count` | int | yes | Positive number of periods |
| `payment_frequency` | string | yes | `weekly`, `fortnightly`, `monthly`, `quarterly`, `bi-annual`, `annual` |

Quote date and disbursement date are not part of this contract.

Example:

```text
consumer.person_id: person-active
consumer.name: Test Consumer
consumer.id_number: 0000000000000
requested_amount_cents: 150000
product_type: short_term
term_count: 6
payment_frequency: monthly
```

## Response: approval

`Approval`, `kind = approval`.

| Field | Type | Notes |
| --- | --- | --- |
| `application_number` | string | Dummy format `APP-` plus 8 digits, starting at `APP-00000001` for each instance. Format is not a locked rule |
| `contractual_periodic_rate_bps` | int | Basis points per payment period. 100 basis points = 1%. Default fixture `240` (2.40% per period). Zero is allowed. The dummy does not clip the rate |
| `term_count` | int | Echo of the request. This dummy does not change the term |
| `payment_frequency` | string | Echo of the request |
| `instalment_cents` | int | Default fixture `25000`. Not calculated from the amount or the rate. Zero is allowed |
| `credit_life_premium_cents` | int | Default fixture `199`. Supplied so the LMS can raise a separate collection. Zero is allowed |
| `short_term_rate_band` | `five_percent`, `three_percent`, or absent | The 5% / 3% flag. It is not the contractual rate |
| `kind` | `approval` | Discriminator |

The dummy does not return a nominal annual rate. Weekly annualisation depends on the year, and the fortnightly period count is not locked. See the open gaps in `docs/LOCKED_DECISIONS.md`.

Default success for the example request:

```text
kind: approval
application_number: APP-00000001
contractual_periodic_rate_bps: 240
term_count: 6
payment_frequency: monthly
instalment_cents: 25000
credit_life_premium_cents: 199
short_term_rate_band: five_percent
```

Changing `requested_amount_cents` or `product_type` does not change the rate, the instalment, the premium, or the flag.

## Response: decline

`Decline`, `kind = decline`.

| Field | Type | Notes |
| --- | --- | --- |
| `application_number` | string | Same dummy sequence as an approval |
| `kind` | `decline` | No rate, term, instalment, premium, or short-term flag |

```text
kind: decline
application_number: APP-00000001
```

A second `decide` on the same instance returns `APP-00000002`. The dummy does not remember an open application and does not refuse a second decision for the same consumer.
