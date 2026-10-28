"""PostgreSQL checks for elections, the audit chain, and tenant isolation.

Skipped when the local cluster cannot apply the migrations.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORG_A = "00000000-0000-4000-8000-0000000000c1"
ORG_B = "00000000-0000-4000-8000-0000000000c2"


def _psql():
    import shutil
    import subprocess

    binary = shutil.which("psql")
    if binary is None:
        pytest.skip("psql is not installed")
    probe = subprocess.run(
        ["sudo", "-u", "postgres", binary, "-d", "postgres", "-c", "SELECT 1"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(probe.stderr.strip() or "postgres is not running")
    return binary


def _run(binary: str, sql: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["sudo", "-u", "postgres", binary, "-d", "postgres", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed.stdout


def test_elections_audit_chain_and_tenant_isolation():
    binary = _psql()
    import subprocess

    present = subprocess.run(
        [
            "sudo", "-u", "postgres", binary, "-d", "postgres", "-tAc",
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'lms' AND table_name = 'cfg_organisation_settings' "
            "AND column_name = 'vat_on_rand_maxima'",
        ],
        capture_output=True,
        text=True,
    )
    if present.returncode != 0:
        raise AssertionError(present.stderr)
    if present.stdout.strip() != "1":
        apply = subprocess.run(
            [
                "sudo", "-u", "postgres", binary, "-d", "postgres",
                "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "db/migrations/0003_elections.sql"),
            ],
            capture_output=True,
            text=True,
        )
        if apply.returncode != 0:
            raise AssertionError(apply.stderr)
    sql = f"""
BEGIN;
-- Negative leniency, a threshold outside 0-100, and a zero campaign.
DO $$
BEGIN
  INSERT INTO lms.cfg_organisation_settings (organisation_id, vat_vendor, actor_kind, leniency_days)
  VALUES ('{ORG_A}', false, 'system', -1);
  RAISE EXCEPTION 'negative leniency accepted';
EXCEPTION WHEN check_violation THEN NULL;
END $$;
DO $$
BEGIN
  INSERT INTO lms.cfg_organisation_settings (
    organisation_id, vat_vendor, actor_kind, full_payment_threshold_percent
  ) VALUES ('{ORG_A}', false, 'system', 101);
  RAISE EXCEPTION 'threshold above 100 accepted';
EXCEPTION WHEN check_violation THEN NULL;
END $$;
INSERT INTO lms.cfg_organisation_settings (
  organisation_id, vat_vendor, actor_kind,
  leniency_days, full_payment_threshold_percent,
  interest_on_deferred_initiation, repo_rate_fall, day_count_code,
  base_rate, discount_rate, vat_on_rand_maxima, late_disbursement, partial_prepayment
) VALUES (
  '{ORG_A}', false, 'system',
  0, 100,
  'none', 'contract_rate', 'actual_actual',
  0.05000000, 0.05000000, 'exclusive', 'adjust_instalment', 'shorten_term'
);
INSERT INTO lms.cfg_product (
  id, organisation_id, product_code, classification_code, enigma_enrolment_code
) VALUES (
  '00000000-0000-4000-8000-0000000000c3', '{ORG_A}', 'micro', 'short_term', 'micro'
);
INSERT INTO lms.cfg_product_terms (
  id, product_id, version, status, effective_from, day_count_code,
  rate_kind, monthly_rate, base_rate, discount_rate
) VALUES (
  '00000000-0000-4000-8000-0000000000c4',
  '00000000-0000-4000-8000-0000000000c3',
  1, 'draft', DATE '2026-10-28', 'actual_actual',
  'fixed_monthly', 0, 0.05000000, 0.05000000
);
SELECT monthly_rate FROM lms.cfg_product_terms
WHERE id = '00000000-0000-4000-8000-0000000000c4';

-- Audit chain and tenant isolation, as the runtime role.
SET ROLE lms_app;
SELECT set_config('lms.organisation_id', '{ORG_A}', true);
INSERT INTO lms.audit_event (
  occurred_at, event_id, organisation_id, event_type, actor_kind, correlation_id, amount_cents
) VALUES (
  TIMESTAMPTZ '2026-10-28 00:00:00+00',
  '00000000-0000-4000-8000-0000000000d1',
  '{ORG_A}', 'PAYMENT_RECEIVED', 'system',
  '00000000-0000-4000-8000-0000000000e1', 100
);
INSERT INTO lms.audit_event (
  occurred_at, event_id, organisation_id, event_type, actor_kind, correlation_id, amount_cents
) VALUES (
  TIMESTAMPTZ '2026-10-28 00:00:01+00',
  '00000000-0000-4000-8000-0000000000d2',
  '{ORG_A}', 'PAYMENT_ALLOCATED', 'system',
  '00000000-0000-4000-8000-0000000000e1', 100
);
SELECT format(
  'RESULT chain=%s seq=%s tariff=%s',
  (
    SELECT encode(a.row_hash, 'hex') = encode(b.previous_hash, 'hex')
    FROM lms.audit_event AS a
    JOIN lms.audit_event AS b
      ON b.event_id = '00000000-0000-4000-8000-0000000000d2'
    WHERE a.event_id = '00000000-0000-4000-8000-0000000000d1'
  ),
  (
    SELECT string_agg(recognition_sequence::text, ',' ORDER BY recognition_sequence)
    FROM lms.audit_event
  ),
  (SELECT count(*) FROM lms.ref_tariff_amount)
);
SELECT set_config('lms.organisation_id', '{ORG_B}', true);
SELECT format('RESULT other=%s', (SELECT count(*) FROM lms.audit_event));
ROLLBACK;
"""
    output = _run(binary, sql)
    assert "0.00000000" in output
    assert "RESULT chain=t seq=1,2 tariff=0" in output
    assert "RESULT other=0" in output
