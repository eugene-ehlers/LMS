"""Pytest output note for the three smoke failures this suite leaves in place."""

KNOWN_OPEN_SEQUENCING_GAPS = (
    "tests/test_layer0_smoke.py::test_same_day_capitalisation_is_not_applied_before_the_receipt",
    "tests/test_layer0_smoke.py::test_rejected_statement_leaves_no_interest_bill",
    "tests/test_layer1_smoke.py::test_layer1_smoke",
)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    terminalreporter.write_sep("-", "Known open sequencing gaps (left failing)")
    terminalreporter.write_line(
        "Same-day capitalisation, a rejected statement that still posts interest, "
        "and the layer 1 smoke are open gaps. Locked rules were not changed to make them pass."
    )
    for node in KNOWN_OPEN_SEQUENCING_GAPS:
        terminalreporter.write_line(node)
