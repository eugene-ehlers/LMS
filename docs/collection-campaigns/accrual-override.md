# Accrual override

During a campaign the ledger posts the day's interest with the existing accrual. The collection-campaign service only chooses the periodic rate.

```
POST /v1/organisations/{organisation_id}/loans/{loan_id}/collection-campaign-accruals
```

```json
{
  "recognised_at": "2026-03-09T08:00:00+02:00",
  "interest_cap_present": true
}
```

`CollectionCampaigns.accrue` does three things:

1. If no applied rate reduction covers that Johannesburg date, it calls `Ledger.accrue_day` with no override. The contractual rate is the rate the ledger already uses, including an origination discount that is still in force. A campaign that only reduces a fee or only grants a payment holiday leaves the rate override unset.
2. If a rate reduction covers the date, it reads `Ledger.contractual_periodic_rate` (the same `_rate_and_divisor` path, and it does not post).
3. It subtracts `rate_reduction` with `lms_config.locked.campaign_rate`. The result is `periodic_rate_override` on `Ledger.accrue_day`. Zeroing the rate means the reduction equals that day's contractual rate. A stored reduction of zero is not a rate change.

`Ledger.accrue_day` still calls `daily_interest_rands` with the account's interest base, day-count weight, and divisor. The override replaces only the rate value. A rate above the contractual rate is `rate-increase` and is not posted. Zero is a normal rate: `daily_interest_rands` returns zero and the call does not fail.

`campaign_rate` is called with `discount_fallen_away` left false. The origination fall-away flag is already inside the contractual rate from step 2. Passing it again would drop the collection reduction.

Section 28 gives each rate or fee change its own duration.

| Scope | When the reduced value is used |
| --- | --- |
| `campaign_period` | From `start_date` through `end_date`, inclusive on the reading in [gaps.md](gaps.md). After `end_date` the original resumes. |
| `rest_of_term` | From `start_date` through the contractual end copied onto the application, including dates after `end_date`. The original does not resume at the campaign end. It resumes after that contractual end. |

A null `end_date` is open-ended. A `campaign_period` reduction then has no end at which to resume, so it keeps applying until staff set an end date. Setting that date ends the campaign: the original rate and fees resume on the next recognition date. A campaign that started open-ended is not treated as permanently open once an end date is stored. The other reading of "unless the campaign was open-ended" is named in [gaps.md](gaps.md).

A `rest_of_term` reduction still runs through the contractual end after staff set an end date. The payment holiday does not. It follows the campaign window only.

The originals stored on the application stay the disclosure copy. Campaign values are not written onto the loan. For a campaign-period change they are the accrual inputs during that window. For a rest-of-term change they are the accrual inputs until the contractual end. That is how the two section 28 sentences are read together: "used for accrual during the campaign period", and "for the campaign period or the rest of the term".

Servicing statement accrual uses the same override when `Servicing.collection_campaigns` is set. With that field left unset, statement accrual is unchanged.

## Fees

`service_fee_for_levy` subtracts the service-fee reduction with `lms.calc.fees.apply_ex_vat_discount` and returns the ex-VAT cents, on the same duration as `fee_scope`. `Ledger.levy_service_fee` then prices VAT and the monthly cap. The campaign module does not price the fee itself. A date outside that duration is levied at the contractual cents.

`levy_charge` has no VAT of its own. A non-service reduction uses `apply_ex_vat_discount` at a VAT rate of 0 so the calculator's floor applies and this module does not invent VAT. The reduced cents are passed to `Ledger.levy_charge`.

A reduction at or above the ex-VAT fee becomes R0 inside `apply_ex_vat_discount`. A negative reduction is refused before that call.

## Payment holiday

A skipped due date is stored on the application. It does not change `schedule_line`, `contractual_end`, or the contractual instalment amount. The skip is only a due date inside the campaign window. A rest-of-term rate does not extend the holiday.

`Ledger.flag_default(..., instalment_skipped=True)` returns false and does not open or close an in-duplum episode. `CollectionCampaigns.flag_default` sets that flag from the stored skips.

`Collections.observe` ignores a skipped due date when recording a new breach. If the only remaining miss is a skipped instalment, it does not close an open episode. Interest billed while an episode is open still increases that episode's accrued charges, unless the campaign rate for the day is zero.

Section 126 allocation is unchanged. A voluntary receipt can still reduce a contractual slice whose date has arrived. Whether allocation should ignore a skipped slice is not locked. See [gaps.md](gaps.md).
