# LMS Open Issues

Issues that are acceptable for dummy and test implementations but must be closed before production.

Each issue is classified as:
- **Decide later**: a rule or design choice that is not yet needed. Close when the case becomes real.
- **Rule change**: a locked decision must be updated before production.
- **Code change**: existing code must be updated before production.
- **Database change**: a schema or migration change is required before production.

Last updated: 2026-10-28

## Dummies (Agent A)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| D1 | Wire format for rate, term, and application number is not locked. Dummy uses integer basis points, term count plus frequency, and APP- plus eight digits. | Decide later | Lock the wire format when a real decision engine is integrated. Code and database already store the values; only the contract needs a lock. |
| D2 | Service address is returned only from the booking identity read. Organisation context does not return addresses. | Decide later | Confirm with Enigma whether organisation context should return addresses. No LMS change until Enigma exposes the field. |
| D3 | When the name or ID number on the application differs from the Enigma booking read, which value is frozen is not locked. | Decide later | Lock the rule when a real case arises. Dummy does not reconcile them. |

## Notifications (Agent D)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| N1 | Layer 1 has no read-only readiness method. The push reads already-issued statements. | Code change | Add a read-only method on Documents that returns whether a statement for a period has already been issued, without calling issue_statement. |
| N2 | Enigma has no consumer-registration operation that avoids contact details. Dummy answers until Enigma exposes one. | Decide later | Enigma must expose a registration check that does not return email or mobile. LMS code already fails closed. |
| N3 | "One month" between successive Day-1 statements has no day count or calendar boundary. | Rule change | Lock the calendar boundary (calendar month, or 30 days from previous statement) in Decision 12. |
| N4 | A stored statement has no section 21 classification and no pure-hosting flag. A blank NCR number fails closed. | Database change | Add a classification column (short_term, unsecured, pure_hosting, zero_cost, cpa_laybye) to the statement or agreement so the NCR exemption can be applied. |
| N5 | NCR character format, call-centre role name, Enigma page URLs, and machine action for the push are not locked. | Decide later | Lock each when the real Enigma and push provider are integrated. Current code fails closed on missing values. |

## Campaigns and elections (Agent B)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| C1 | Fall-away choice and trigger are stored on the campaign and also as an organisation election with a product override. The lock does not say which value applies when they differ. | Rule change | Add a sentence to Decision 3 or Decision 19 that names the precedence (campaign value wins, or organisation value wins). |
| C2 | The lock does not say which campaign applies when more than one period contains the recognition date. Intake stores nothing. | Rule change | Lock the rule (most recent campaign, or fail closed) in Decision 3. |
| C3 | The lock does not say whether a qualifying loan keeps the decision-engine rate or uses the campaign net. Both are stored. | Rule change | Lock the rule in Decision 3 or Decision 13. |
| C4 | Decision 8 names a residual default of R100. Decision 19 says an unset election fails closed and also names that default. A null threshold is left unset and resolve fails. | Rule change | Decide whether R100 is a platform default that fills when unset, or whether unset always fails closed. Update Decision 8 or Decision 19. |
| C5 | campaign_rate still rejects a discount above the base. | Code change | Update campaign_rate to floor the net at 0 % instead of rejecting the pair. |
| C6 | resolve_residual_threshold_cents still fills R50 (5 000 cents) when both levels are null. | Code change | Update the function to fail closed or to fill R100, depending on the resolution of C4. |

## Payment rails (Agent C)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| P1 | Section 19 does not name debit_orders_enabled as the section 4 automation switch. | Rule change | Add debit_orders_enabled to the elections in Decision 19. |
| P2 | Loan-number character pattern and stored contractual instalment are unset. The loan line reads the amount still outstanding on that due date. | Decide later | Lock the loan-number pattern when the real numbering scheme is finalised. The outstanding-amount approach is acceptable for testing. |
| P3 | Bankserv has no DebiCheck record type and no stated hash algorithm. Consumer homing account and 10-character abbreviated name are not LMS fields. A credit-life receipt has no insurer hand-off. | Decide later | Lock the Bankserv layout details and the insurer hand-off when the real rail and insurer contracts are in place. |
| P4 | Whether interest accruing on the due date is itself due that day is unsettled. The rail bills the whole unbilled memo through bill_interest. | Rule change | Lock whether interest accruing on the due date is due that day in Decision 1 or Decision 8. |

## Regulatory extracts (Agent E)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| R1 | Decision 21 says "micro" and "Laybye/BNPL". The ledger stores short_term, unsecured, zero_cost, and cpa_layby. pure_hosting is not a column. The map is not locked. A missing pure_hosting value fails closed when a row would require the number. | Rule change | Lock the classification map in Decision 21. Add pure_hosting as a column or as a value that the extract can read. |
| R2 | The ledger can post a full write-off journal. The Form 39 write-off cell stays empty. | Decide later | Lock whether Form 39 should include write-offs when the real Form 39 layout is confirmed. |

## Daily batch status (Agent J)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| J1 | `docs/LOCKED_DECISIONS.md` contains only "See /tmp/locked_updated.md - content too large for this call, will upload in parts if needed". That file is not present. The last complete text is commit `71aac64184500fe55390c3c822bf74c796fa6127` (same body as `401b3c1dacf2373c7a7678ec2b676002b4512c02`). Commit `f75d1be` replaced it with `PLACEHOLDER`. Commit `ecffee7` replaced it with the stub. The commit subject mentions a collection-campaigns section. The section body was never written. | Rule change | Restore the locked decisions text. Add the collection-campaigns section only from wording that is actually supplied. Do not invent that section. The daily batch followed the last complete text plus the communication, orchestration, and collections-split documents, and did not edit the stub. |
| J2 | Decision 1 says the day starts at 00:00 and does not name a time zone. | Rule change | Lock Africa/Johannesburg on Decision 1, or name a different zone. This batch uses Africa/Johannesburg because the batch requirement states it. The stored offset is +02:00. |
| J3 | Orchestration section 1 calls Servicing.accept_payment before the default outcome. The daily batch calls accrue, capitalise, and default check only. | Rule change | Lock whether the morning default check runs after allocation of a receipt recognised the same day. Until then, this batch does not allocate, and the default check cannot see that receipt unless allocation already happened outside the batch. |
| J4 | The morning default check has no locked module name. | Decide later | Name the module. This batch calls `default_check`. It does not call Collections.observe, which section 3 uses when a collections default is flagged. |
| J5 | "If the batch does not complete" does not say whether account failures on a finished batch block the next recognition date. | Rule change | Lock the gate. Until then: a finished batch has completed; account failures are stored, audited as `failed`, and shown as the last failed run; they do not raise the did-not-complete alert and do not block the next date. Only an unfinished run blocks, until a later finish of that same date or an explicit skip. |
| J6 | A retry after an incomplete or skipped run calls accrue, capitalise, and default check again for every account. | Rule change | Lock idempotency. A crash after some accounts were calculated can calculate them again on retry. |
| J7 | Decision 23 requires the staff identity from Enigma. Decision 15 fails closed on an Enigma timeout. No role is locked for running or skipping the daily batch. | Rule change | Lock the actor and the role for an attended or unattended run. This batch does not call Enigma. A missing `actor_id` fails closed and is not audited. A supplied person id is stored. |
| J8 | Nothing requires recognition dates to be consecutive calendar days. | Decide later | Lock whether a calendar day that was never started blocks a later date. This batch allows the gap when no unfinished run is outstanding. |
| J9 | A recognition date whose batch has finished cannot be started again, including when accounts failed. | Rule change | Lock whether a finished day can be repeated. This batch refuses the second start so the day is not calculated twice. |
| J10 | No alert channel or crash timeout is locked. | Decide later | Lock how an operator is notified, and how a killed run is distinguished from a run that is still working. The alert is a stored row returned by the status query. A hard stop leaves the run in progress. The alert row is written when a later start is refused or the run is skipped. No timeout is applied. |
| J11 | Communication section 4 also requires the last status of a batch or UI action by account. | Code change | Add the account query and the UI-action status before production. This batch queries by organisation only. |
| J12 | The run is given its account identifiers. There is no ledger account registry in this repository. An empty list finishes with zero accounts. | Code change | Take the account list from the ledger when the ledger exists, and fail closed if the ledger cannot supply it. |

## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 11 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 14 | Update docs/LOCKED_DECISIONS.md. |
| Code change | 5 | Update the existing functions. |
| Database change | 1 | Add a classification column. |

Issues from Agents A, B, C, D, E, and J are recorded so they can be closed before production. Counts match the rows above.
