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

1. If no application covers that Johannesburg date, it calls `Ledger.accrue_day` with no override. The contractual rate is the rate the ledger already uses, including an origination discount that is still in force.
2. If an application covers the date, it reads `Ledger.contractual_periodic_rate` (the same `_rate_and_divisor` path, and it does not post).
3. It subtracts `rate_reduction` with `lms_config.locked.campaign_rate`. The result is `periodic_rate_override` on `Ledger.accrue_day`.

`Ledger.accrue_day` still calls `daily_interest_rands` with the account's interest base, day-count weight, and divisor. The override replaces only the rate value. A rate above the contractual rate is `rate-increase` and is not posted. Zero is a normal rate: `daily_interest_rands` returns zero and the call does not fail.

`campaign_rate` is called with `discount_fallen_away` left false. The origination fall-away flag is already inside the contractual rate from step 2. Passing it again would drop the collection reduction.

When the recognition date is after `end_date`, the override is absent and the original rate resumes. An open-ended campaign (`end_date` null) keeps the override until staff set an end date.

Servicing statement accrual uses the same override when `Servicing.collection_campaigns` is set. With that field left unset, statement accrual is unchanged.

## Fees

`service_fee_for_levy` subtracts the service-fee reduction with `lms.calc.fees.apply_ex_vat_discount` and returns the ex-VAT cents. `Ledger.levy_service_fee` then prices VAT and the monthly cap. The campaign module does not price the fee itself.

`levy_charge` has no VAT of its own. A non-service reduction uses `apply_ex_vat_discount` at a VAT rate of 0 so the calculator's floor applies and this module does not invent VAT. The reduced cents are passed to `Ledger.levy_charge`.

A reduction at or above the ex-VAT fee becomes R0 inside `apply_ex_vat_discount`. A negative reduction is refused before that call.

## Payment holiday

A skipped due date is stored on the application. It does not change `schedule_line` or `contractual_end`.

`Ledger.flag_default(..., instalment_skipped=True)` returns false and does not open or close an in-duplum episode. `CollectionCampaigns.flag_default` sets that flag from the stored skips.

`Collections.observe` ignores a skipped due date when recording a new breach. If the only remaining miss is a skipped instalment, it does not close an open episode. Interest billed while an episode is open still increases that episode's accrued charges, unless the campaign rate for the day is zero.

Section 126 allocation is unchanged. A voluntary receipt can still reduce a contractual slice whose date has arrived. Whether allocation should ignore a skipped slice is not locked. See [gaps.md](gaps.md).
