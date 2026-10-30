# Restructure gaps

These points are not settled by the locked decisions. This path does not invent a value for them. The same items are recorded in `docs/OPEN_ISSUES.md` where they must be closed before production.

`docs/LOCKED_DECISIONS.md` on `main` does not contain the decisions. The file points at `/tmp/locked_updated.md`, which is not in the repository. The text followed here is the last complete copy (commit `401b3c1`) and section 28 on `cursor/restore-locked-decisions-ccde`. This change does not edit the locked file. Restoring it is a separate change (open pull request 35).

## Not locked

| Point | What this path does |
| --- | --- |
| Decision 25 allows one loan number per application, with a Laybye exception only. It does not say whether a restructure agreement receives a new loan number. | No loan number is allocated. The new agreement has its own agreement id and stores the application number the engine supplied. |
| Decision 13 says the LMS checks that calculations stay within the Act for the supplied rate. | The rate is stored. The calculation engine is not on this branch, and no Act maximum is added here. |
| Decision 23 requires a signed-in role and does not name a restructure role. | An active Enigma staff identity is required. The roles presented are stored. No role name is invented. |
| A payment-frequency change, with the same term count and the same instalment, is not classified. | The request fails closed. No agreement is created. |
| Decision 28 requires five business days' notice before a collection-campaign change. It does not say that a consented restructure needs that notice. | Consent is required. No notice interval is added. |
| The live status token for the new agreement is not named. | The new agreement is stored as `active`. The original is stored as `restructured`, which is the word the restructure instruction uses. |
| The ledger on the unmerged branch stores a balance as the sum of entries. | This path transfers the outstanding balance it is given, in integer cents. |
| The organisation and product election store is on another branch. | Elections are frozen from the row supplied to this request. A missing value fails closed. |
| Open point D1: the rate wire format is not locked. | The integer the engine supplies is stored as `contractual_periodic_rate_bps`. It is not treated as a locked wire format. |
| Open point D3: which identity wins when two sources differ. | A difference from the identity frozen on the original agreement fails closed. Neither value is chosen as the winner. |
| Open issue C4: residual threshold R100 versus unset fails closed. | An unset residual fails closed. R100 is not filled. |
| Decision 14 spells the frequency `bi-annual`. The ledger branch stores `bi_annual`. | This path accepts the Decision 14 spelling only. |
| A naive `recognised_at` has no Johannesburg day (Decision 1), and the audit row requires that day. | The caller receives the failure. The row is not written. |

## Out of scope

Early settlement, a collection campaign (a rate or fee change that does not change the term or the instalment), and settlement re-advance are refused with a specific reason. Those paths are not implemented here.

## Orchestration

`docs/ORCHESTRATION.md` had no restructure flow. Section 9 now records the steps in the restructure instruction and Decisions 13, 16, 19, and 23. No accrual, capitalisation, or campaign step was added.
