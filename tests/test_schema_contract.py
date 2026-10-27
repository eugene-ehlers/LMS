"""The migration, the seed, and the engine read path name the same things."""

from pathlib import Path

from lms_config.calendar import public_holidays
from lms_config.context import (
    CUSTOMER_SETTINGS_SQL,
    ENGINE_READ_STEPS,
    INTEREST_CAP_SQL,
    PUBLISHED_TERMS_SQL,
    REFERENCE_RATE_SQL,
    SHORT_TERM_ORDINAL_SQL,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "db" / "migrations" / "0001_lms_owned.sql").read_text()
SEED = (ROOT / "db" / "seed" / "001_reference.sql").read_text()


def test_engine_steps_include_the_pin_the_ceiling_and_the_audit():
    assert ENGINE_READ_STEPS[0] == "agreement_pin"
    assert "customer_settings" in ENGINE_READ_STEPS
    assert "interest_cap" in ENGINE_READ_STEPS
    assert "reference_rate" in ENGINE_READ_STEPS
    assert ENGINE_READ_STEPS[-1] == "post_and_audit"
    assert "feature_flag" not in ENGINE_READ_STEPS
    assert "brand" not in ENGINE_READ_STEPS


def test_read_sql_uses_tables_this_migration_owns_except_the_agreement():
    assert "lms.cfg_product_terms" in PUBLISHED_TERMS_SQL
    assert "leniency_days" in CUSTOMER_SETTINGS_SQL
    assert "full_payment_threshold_percent" in CUSTOMER_SETTINGS_SQL
    assert "base_rate" in CUSTOMER_SETTINGS_SQL
    assert "discount_rate" in CUSTOMER_SETTINGS_SQL
    assert "lms.ref_interest_cap" in INTEREST_CAP_SQL
    assert "lms.ref_reference_rate" in REFERENCE_RATE_SQL
    assert "confidence = 'confirmed'" in REFERENCE_RATE_SQL
    assert "servicing.agreement" in SHORT_TERM_ORDINAL_SQL
    assert "CREATE TABLE lms.agreement" not in MIGRATION
    assert "CREATE TABLE servicing.agreement" not in MIGRATION
    for name in (
        "cfg_product_terms",
        "ref_interest_cap",
        "ref_reference_rate",
        "ref_interpretation_set",
        "audit_event",
    ):
        assert f"CREATE TABLE lms.{name}" in MIGRATION


def test_locked_decision_columns_are_in_the_second_migration():
    migration = (ROOT / "db" / "migrations" / "0002_locked_decisions.sql").read_text()
    for name in (
        "leniency_days",
        "full_payment_threshold_percent",
        "base_rate",
        "discount_rate",
        "interest_on_deferred_initiation",
        "repo_rate_fall",
        "actual_actual",
        "thirty_360",
    ):
        assert name in migration
    assert "docs/LOCKED_DECISIONS.md" in migration


def test_seed_carries_the_gazetted_figures_the_tests_charge():
    assert "0.05000000" in SEED
    assert "0.03000000" in SEED
    assert "0.21000000" in SEED
    assert "0.07250000" in SEED
    assert "6000" in SEED
    assert "800000" in SEED
    assert "1500000" in SEED
    assert "25000000" in SEED
    assert "2016-05-06" in SEED
    assert "2026-09-25" in SEED
    assert "cash_advanced" in SEED
    assert "cumulative" in SEED
    assert "first_disbursed_loan" in SEED
    # The May 2026 7.00% figure is deliberately not a confirmed row.
    assert "0.07000000" not in SEED


def test_seed_holidays_match_the_calendar_function():
    for year in range(2026, 2033):
        for day, _name, _source in public_holidays(year):
            assert day.isoformat() in SEED
