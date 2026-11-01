# Change control

How a locked rule changes, and how a code change is reviewed. This note does not change a rule.

## A locked rule

`docs/LOCKED_DECISIONS.md` is the source of truth. The standing instruction in that file says a locked decision is not reopened without an explicit change request, and that a gap is raised so the file can be updated where every reader can see it.

The update is:

1. Edit `docs/LOCKED_DECISIONS.md`. State the new sentence in the section it belongs to. Leave the previous reading visible only as a superseded note when the file already records one that way.
2. Open a pull request whose diff is that edit, and any design note that would otherwise contradict the new sentence.
3. Update the code and the tests that cite the section. A comment, an error string, or a test that still quotes the old sentence is updated in the same change, or in a follow-up pull request that names the decision section.

Code does not become a second rule. Where a design note and the locked file disagree, the locked file wins (`docs/servicing/primary-flows.md`; `docs/layer2/README.md`). An open gap is recorded in `docs/OPEN_ISSUES.md` or in the gaps note for that layer. It is not closed by silently choosing a reading (`docs/LOCKED_DECISIONS.md`, standing instruction; `docs/ORCHESTRATION.md`).

`main` currently holds a stub in place of the decision text. Restoring or editing the rule means replacing that stub with the full document, not appending a sentence to the stub (`docs/OPEN_ISSUES.md`, K6).

## A code change

A code change is a pull request. Review checks three things:

1. The pull request describes the behaviour. It names the locked section, or the existing design note, that the change implements.
2. The tests for that behaviour pass. A test that is documented as an open sequencing gap stays failed on purpose. Those tests are listed in `docs/testing/known-open-sequencing-gaps.md`. Closing one of them by changing a locked rule is a locked-rule change, not a quiet test edit.
3. The change does not invent a default the lock left unset. Unset elections fail closed, except the residual write-off threshold, which fills R100 (`docs/LOCKED_DECISIONS.md` §19).

Configuration writes already cite the mandate string they check (`docs/layer2/routes.md`). A new write follows that pattern: an existing role string, or a new string only after Decision 23 names it.

The audit record for a configuration write remains the sealed row: person id from Enigma, timestamp, before and after, `previous_hash`, `row_hash`, and `recognition_sequence` (`docs/LOCKED_DECISIONS.md` §23; `docs/audit/audit-security.md`).
