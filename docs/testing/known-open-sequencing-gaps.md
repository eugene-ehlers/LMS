# Known open sequencing gaps

These three tests fail on purpose. They record open sequencing gaps. They are not defects to close by changing a locked rule, and this end-to-end pass does not edit them.

- `tests/test_layer0_smoke.py::test_same_day_capitalisation_is_not_applied_before_the_receipt`
- `tests/test_layer0_smoke.py::test_rejected_statement_leaves_no_interest_bill`
- `tests/test_layer1_smoke.py::test_layer1_smoke`

Same-day capitalisation: on a calendar day, locked decisions 1 and 8 say amounts that become due that day are capitalised at 00:00 before a receipt recognised that day is allocated. The ledger follows recognition order and does not reorder a payment behind that day's capitalisation. The end-to-end statement test issues the statement first and posts the receipt on a later recognition date. It does not treat the current same-day order as the rule.

A rejected statement can still leave an interest bill behind when a required statement input is missing. That smoke records the gap. Statement generation was not reworked to make the smoke pass.

The Layer 1 smoke fails because its gap list is still non-empty. Those gaps stay open.
