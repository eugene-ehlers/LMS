# Stored restructure

Amounts are integer cents. A bool or a float is rejected. Zero is a real amount.

## Original agreement

Held before the restructure. This path reads it and does not originate it.

| Field | Rule |
| --- | --- |
| `agreement_id`, `organisation_id`, `person_id` | Opaque ids. |
| `outstanding_balance_cents` | Integer cents. Transferred in full. The original is then 0. |
| `contractual_instalment_cents` | The contractual instalment already stored. Left unchanged on the original. |
| `term_count`, `payment_frequency` | The contractual term already stored. Payment frequency is one of weekly, fortnightly, monthly, quarterly, bi-annual, annual (Decision 14). |
| `contractual_periodic_rate_bps` | The integer rate already stored. |
| `application_number` | The application number already linked to this agreement. |
| `frozen_full_name`, `frozen_id_number`, `frozen_service_address` | Frozen at booking (Decision 16). A later restructure does not rewrite them. |
| `status` | `active` can be restructured. After success the status is `restructured`. |

## New agreement

Created by a successful restructure and linked with `original_agreement_id`.

| Field | Rule |
| --- | --- |
| `outstanding_balance_cents` | The balance transferred from the original, in integer cents. |
| `contractual_instalment_cents` | The instalment the decision engine supplied. Frozen. |
| `term_count`, `payment_frequency` | The term the decision engine supplied. Frozen. |
| `contractual_periodic_rate_bps` | The rate integer the decision engine supplied. Frozen. Not used to recalculate the instalment. |
| `application_number` | The application number the decision engine supplied. A second loan number is not allocated. See [gaps.md](gaps.md). |
| `elections` | The Decision 19 row, frozen. A later organisation edit does not rewrite it. |
| `client_consent` | `true`. Frozen. |
| `consent_date` | The calendar date the client consented. Frozen. |
| `recognised_at` | 00:00 Africa/Johannesburg on the recognition date. Frozen. |
| Identity fields | The name, ID number, and service address that matched the original. Frozen. |
| `status` | `active`. The token for a live agreement is not locked. See gaps. |

The original stores `restructured_to_agreement_id`.

## Elections

Required. The product-or-organisation resolution lives on another branch. This path freezes the row it is given and fails closed when a required value is missing. It does not fill the residual threshold with R100 (open issue C4).

| Field | Allowed values |
| --- | --- |
| `vat_on_rand_maxima` | `exclusive`, `inclusive` |
| `late_disbursement` | `adjust_instalment`, `keep_instalment` |
| `partial_prepayment` | `shorten_term`, `drop_instalment` |
| `interest_on_deferred_initiation` | `none`, `permitted` |
| `repo_rate_fall` | `contract_rate`, `lower_of_contract_and_cap` |
| `in_duplum_trigger` | `contractual_breach`, `collections_default` |
| `residual_write_off_threshold_cents` | Integer cents, zero or greater |
| `campaign_fall_away_choice` | `falls_away_on_default`, `does_not_fall_away` |
| `campaign_fall_away_trigger` | `contractual_breach` or `collections_default` when the choice falls away. Absent when it does not |

## Balance transfer

The outstanding balance is one integer. On success it moves from the original agreement to the new agreement. The ledger branch does not store a balance column; a bucket balance there is the sum of entries. This path transfers the outstanding balance it is given and does not post bucket journals. See gaps.

## Audit

| Field | Rule |
| --- | --- |
| `actor_person_id` | Staff person id from Enigma. Null only when the failure is a missing staff identity. |
| `occurred_at` | 00:00 Africa/Johannesburg. |
| `outcome` | `success` or `failure`. |
| `roles` | The role names presented on the call. |
| `payload` | On success: the ids, the transferred cents, the stored instalment, the consent flag, and the consent date. On failure: the reason. |
