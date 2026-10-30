# Campaign schema

In-process records live on `CollectionCampaigns`. The same shape is in `db/migrations/0008_collection_campaigns.sql`. Dates are Johannesburg recognition dates. Money is integer cents. Rates are decimals in the same unit as the contractual periodic rate (monthly on a short-term loan, annual on an unsecured loan).

## `collection_campaign`

| Column | Meaning |
| --- | --- |
| `organisation_id` | Opaque Enigma organisation id. A campaign does not cross organisations. |
| `campaign_id` | LMS id. |
| `start_date` | First recognition date on which the overlay applies. |
| `end_date` | Last recognition date on which it applies, or null when the campaign is open-ended. |
| `rate_reduction` | Non-negative reduction subtracted from the contractual periodic rate. Zero leaves the rate unchanged. Zeroing the rate means a reduction equal to that day's contractual rate. |
| `rate_scope` | `campaign_period` or `rest_of_term` when `rate_reduction` is positive. Null when the rate is unchanged. Not defaulted. |
| `fee_scope` | `campaign_period` or `rest_of_term` when at least one fee reduction is positive. Null when no fee is reduced. Not defaulted. |
| `payment_holiday` | When true, contractual due dates inside the campaign period are skipped. The schedule is not rewritten. A holiday has no rest-of-term scope. |
| `notice_date` | Date the section 104(2) written notice was given. The notice itself is not stored. |
| `notice_business_days` | Always 5. Recorded so the row shows the statutory interval. Not an election. |
| `created_by` | Staff Enigma person id. |
| `created_at` | Aware timestamp of the create. The recognition date is that timestamp in Africa/Johannesburg. |

`collection_campaign_fee` stores one row per reduced fee type: `initiation`, `service`, `credit_insurance`, `default_administration`, `collection_costs`, `additional_monthly`. `reduction_cents` is zero or positive. A missing row means that fee is not part of the campaign. `fee_scope` is null exactly when every stored reduction is zero (or there is no fee row). That match is enforced in the service. The fee amounts live in the child table, so the migration does not add a cross-table check.

## Originals, stored separately

`collection_campaign_application` copies, at apply time:

- contractual base rate and origination discount
- contractual periodic rate on the apply recognition date
- contractual end date

`collection_campaign_fee_original` copies each registered contractual fee in cents.

`collection_campaign_instalment` copies each contractual schedule line (`due_on`, `principal_cents`). `skipped` marks a payment-holiday due date. These rows are not `schedule_line` and are not a new version of the contract.

Applying, editing, or ending a campaign does not update `loan_account`, `election_snapshot`, `schedule_version`, or `schedule_line`, and it does not insert a loan. Section 95: a collection campaign is not a new credit agreement.

## Audit

Create, edit, end, and apply append `COLLECTION_CAMPAIGN_CHANGED` on the operational audit log. The row stores:

- who: `enigma_person_id` (the staff actor)
- when: `occurred_at`, plus `recognition_date` in the payload (Johannesburg date)
- accounts: `loan_ids`
- before and after: payload `before` and `after`

An apply's before and after both carry the contractual instalments and the contractual end. Those values match. The after block adds `effective_rate`, `fee_reductions_cents`, `rate_scope`, and `fee_scope`. Create, edit, and end store the same scopes on the campaign before and after.
