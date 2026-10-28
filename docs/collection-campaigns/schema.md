# Campaign schema

In-process records live on `CollectionCampaigns`. The same shape is in `db/migrations/0008_collection_campaigns.sql`. Dates are Johannesburg recognition dates. Money is integer cents. Rates are decimals in the same unit as the contractual periodic rate (monthly on a short-term loan, annual on an unsecured loan).

## `collection_campaign`

| Column | Meaning |
| --- | --- |
| `organisation_id` | Opaque Enigma organisation id. A campaign does not cross organisations. |
| `campaign_id` | LMS id. |
| `start_date` | First recognition date on which the overlay applies. |
| `end_date` | Last recognition date on which it applies, or null when the campaign is open-ended. |
| `rate_reduction` | Non-negative reduction subtracted from the contractual periodic rate. Zero leaves the rate unchanged. |
| `payment_holiday` | When true, contractual due dates inside the period are skipped. The schedule is not rewritten. |
| `notice_date` | Date the section 104(2) written notice was given. The notice itself is not stored. |
| `notice_business_days` | Always 5. Recorded so the row shows the statutory interval. Not an election. |
| `created_by` | Staff Enigma person id. |
| `created_at` | Aware timestamp of the create. The recognition date is that timestamp in Africa/Johannesburg. |

`collection_campaign_fee` stores one row per reduced fee type: `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`. `reduction_cents` is zero or positive. A missing row means that fee is not part of the campaign.

## Originals, stored separately

`collection_campaign_application` copies, at apply time:

- contractual base rate and origination discount
- contractual periodic rate on the apply recognition date
- contractual end date

`collection_campaign_fee_original` copies each registered contractual fee in cents.

`collection_campaign_instalment` copies each contractual schedule line (`due_on`, `principal_cents`). `skipped` marks a payment-holiday due date. These rows are not `schedule_line` and are not a new version of the contract.

Applying, editing, or ending a campaign does not update `loan_account`, `election_snapshot`, `schedule_version`, or `schedule_line`.

## Audit

Create, edit, end, and apply append `COLLECTION_CAMPAIGN_CHANGED` on the operational audit log. The row stores:

- who: `enigma_person_id` (the staff actor)
- when: `occurred_at`, plus `recognition_date` in the payload (Johannesburg date)
- accounts: `loan_ids`
- before and after: payload `before` and `after`

An apply's before and after both carry the contractual instalments and the contractual end. Those values match. The after block adds `effective_rate` and `fee_reductions_cents`.
