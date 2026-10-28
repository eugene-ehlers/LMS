# Staff routes

The staff surface is `lms.staff.api.dispatch`. It does not serve consumer registration, and it does not call statement generation.

Every command carries an aware timestamp in `recognised_at`. The recognition date is `lms_config.calendar.value_date` of that instant: the calendar date in Africa/Johannesburg, treated as 00:00 that day. An instant that is still the previous date in UTC can already be the next Johannesburg date.

Headers on every call:

| Header | Meaning |
| --- | --- |
| `X-Enigma-Person-Id` | Opaque staff person id. Blank fails closed. |
| `X-Enigma-Organisation-Id` | Opaque organisation id. The command's organisation must be this id. |
| `X-Enigma-Roles` | Comma-separated role names returned by Enigma. |
| `X-Enigma-Status` | `active` (default), `timeout`, `ambiguous`, or `suspended`. Anything other than `active` fails closed. |

Timeout and an ambiguous status are HTTP 503. A missing role or a suspended enrolment is HTTP 403. A missing election, a blank compliance field, or a campaign that does not validate is HTTP 422.

Money fields are integer cents. Rates are decimal strings (`"0.05"` is 5 %), not floats.

## Roles

| Role | Commands |
| --- | --- |
| `lms.campaign.write` | Campaign list, create, edit, end, and fee preview |
| `lms.elections.write` | Election list, edit, and resolve |
| `lms.compliance.write` | Compliance read and write |
| `lms.ceiling.platform.write` | Solution-wide ceiling list and write |
| `lms.ceiling.company.write` | Company ceiling list and write |

The audit read accepts any one of those roles. Decision 23 does not name a separate audit role, so this layer does not invent one. Decision intake stores a supplied rate; it requires an active staff identity and does not require one of the write roles above, because the lock does not name an intake role.

## Campaigns

| Method and path | Body |
| --- | --- |
| `GET /v1/staff/organisations/{organisation_id}/campaigns` | none |
| `POST /v1/staff/organisations/{organisation_id}/campaigns` | campaign fields below, plus `recognised_at` |
| `GET /v1/staff/organisations/{organisation_id}/campaigns/{campaign_id}` | none |
| `PATCH /v1/staff/organisations/{organisation_id}/campaigns/{campaign_id}` | the same campaign fields, plus `recognised_at` |
| `POST /v1/staff/organisations/{organisation_id}/campaigns/{campaign_id}/end` | `recognised_at` |
| `POST /v1/staff/organisations/{organisation_id}/campaigns/{campaign_id}/fee-preview` | `kind` (`initiation` or `service`), `ex_vat_cents`, `vat_rate` |

Campaign fields:

| Field | Rule |
| --- | --- |
| `product_id` | String, or null for an organisation campaign |
| `start_date`, `end_date` | `YYYY-MM-DD`. End before start is refused |
| `base_rate`, `discount_rate` | Decimal strings, zero or greater. The net is not submitted |
| `fall_away_choice` | `falls_away_on_default` or `does_not_fall_away` |
| `fall_away_trigger` | `contractual_breach` or `collections_default` when the choice falls away. Null when it does not |
| `initiation_fee_discount_cents`, `service_fee_discount_cents` | Integer cents, zero or greater |

The response adds `net_rate`, `campaign_id`, and `version`. `net_rate` is `lms_config.locked.campaign_rate` when the discount does not exceed the base. When the discount is higher, that function refuses the pair. Decision 3 floors the net at 0 %, so the stored net is `0` in that case. See [gaps](gaps.md).

`end` sets `end_date` to the recognition date when that date is earlier than the stored end, and refuses an end before the start date. Create, edit, and end append an audit row. They do not load or update a decision-intake row, and they do not read the ledger.

A loan qualifies when its recognition date is inside the inclusive start and end dates. The maturity date is ignored, so a term that runs past the campaign end still qualifies. An organisation campaign matches every product. A product campaign matches only that product. Two matches fail the intake. The lock does not say which one to keep.

## Elections

| Method and path | Body |
| --- | --- |
| `GET /v1/staff/organisations/{organisation_id}/elections` | none. Returns the organisation row and each product row, including nulls |
| `PUT /v1/staff/organisations/{organisation_id}/elections` | election object, plus `recognised_at` |
| `GET /v1/staff/organisations/{organisation_id}/products/{product_id}/elections` | none |
| `PUT /v1/staff/organisations/{organisation_id}/products/{product_id}/elections` | election object, plus `recognised_at` |
| `POST /v1/staff/organisations/{organisation_id}/elections/resolve` | optional `product_id` |

`PUT` replaces that level. A null field is unset. A product null inherits the organisation when the caller resolves. Resolve fails closed while any required election is unset at both levels. The field list and the allowed values are in [election-schema](election-schema.md).

## Compliance

| Method and path | Body |
| --- | --- |
| `GET /v1/staff/organisations/{organisation_id}/compliance` | none. Missing row fails closed |
| `PUT /v1/staff/organisations/{organisation_id}/compliance` | the fields below, plus `recognised_at` |

The write calls `lms_config.compliance.ComplianceStore.put`. A blank required field fails closed inside that store. The NCR number is compulsory. A number whose characters are zeros, including `0000000` and a test value such as `NCRCP0000`, is accepted. Trading name may be an empty string: the existing store treats it as regulation 35 "if any". `legal_name` is required by that store in addition to the fields named in decision 21.

| Field | Required text |
| --- | --- |
| `legal_name` | yes |
| `ncr_registration_number` | yes, zeros allowed |
| `trading_name` | present; empty string allowed |
| `physical_address`, `postal_address` | yes |
| `telephone` | yes |
| `bank_name`, `bank_account_number`, `branch_code`, `payment_reference` | yes. These are the payment-account details |

## Operational ceilings

| Method and path | Body |
| --- | --- |
| `GET /v1/staff/ceilings/platform` | none |
| `PUT /v1/staff/ceilings/platform` | `action`, `amount_cents`, `recognised_at` |
| `GET /v1/staff/organisations/{organisation_id}/ceilings` | none |
| `PUT /v1/staff/organisations/{organisation_id}/ceilings` | `action`, `amount_cents`, `recognised_at` |
| `POST /v1/staff/ceilings/apply` | `action`, `amount_cents`, `organisation_id` |

`action` is the command name the later money command will use. This layer does not publish a catalogue of actions. Currency is `ZAR`. Amounts are cents. Zero is a real ceiling.

`apply` reads the platform row and the company row and keeps the lower amount. A missing platform row stops the command. A company row above the platform row does not raise the limit. An amount above the limit is HTTP 403. An amount equal to the limit is allowed. The call does not post a journal and does not write a ceiling.

## Decision intake

`POST /v1/staff/organisations/{organisation_id}/decision-intake`

| Field | Rule |
| --- | --- |
| `application_number` | Required text |
| `supplied_rate` | Decimal string, stored as given |
| `credit_life_premium_cents` | Integer cents, stored as given |
| `product_id` | Optional |
| `maturity_date` | Optional `YYYY-MM-DD`. Not used to decide whether the campaign applies |
| `recognised_at` | Aware timestamp. The recognition date is the Johannesburg date |

The response copies the qualifying campaign's base, discount, net, and fall-away as they stood at this call. No match stores those campaign fields as null and still stores the supplied rate and premium. More than one match stores nothing.

## Audit

`GET /v1/staff/organisations/{organisation_id}/audit`

`from` and `to` are `YYYY-MM-DD` in the body, or `X-From` and `X-To` headers. The range is inclusive on the Johannesburg recognition date of each row. Each row has `enigma_person_id`, `occurred_at`, `recognition_date`, `event_type`, and a payload with `before` and `after`.

Event types: `CAMPAIGN_CREATED`, `CAMPAIGN_EDITED`, `CAMPAIGN_ENDED`, `ELECTION_CHANGED`, `COMPLIANCE_CHANGED`, `CEILING_CHANGED`, `DECISION_INTAKE_STORED`. They are operational. The cent amounts sit in the payload, not in the financial `amount_cents` column.
