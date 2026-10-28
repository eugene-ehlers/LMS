-- LMS-owned configuration, reference data, and audit.
--
-- Enigma owns identity, organisations, memberships, product enrolment,
-- roles, and mandates. Every organisation_id and enigma person id in this
-- schema is an opaque Enigma identifier. There is no foreign key to an
-- organisation or person table, and this migration does not create one.
--
-- Runtime connects as lms_app with lms.organisation_id set to the Enigma
-- organisation for the request. The migration role owns the tables and is
-- not the runtime role.
--
-- Business dates are Johannesburg dates. audit_event.occurred_at is an
-- instant, and partitions are UTC months. Apply this file with TimeZone=UTC.

SET timezone = 'UTC';

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA IF NOT EXISTS lms;

COMMENT ON SCHEMA lms IS
  'Post-origination LMS data that Enigma does not own: product parameters, statutory reference data, and the financial/operational audit log.';

DO $$ BEGIN
  CREATE ROLE lms_app NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE ROLE lms_reader NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- -----------------------------------------------------------------------
-- Vocabulary. Gazette amounts are seeded separately, so a wrong rand
-- figure is a data change rather than a code change.
-- -----------------------------------------------------------------------

CREATE TABLE lms.ref_instrument (
  code text PRIMARY KEY,
  citation text NOT NULL,
  effective_from date NOT NULL
);

COMMENT ON TABLE lms.ref_instrument IS
  'Statute, regulation, or rate-announcement this row of reference data was transcribed from.';

CREATE TABLE lms.ref_credit_classification (
  code text PRIMARY KEY,
  statute_item text,
  rate_period text NOT NULL CHECK (rate_period IN ('year', 'month', 'none')),
  description text NOT NULL
);

COMMENT ON TABLE lms.ref_credit_classification IS
  'NCA Table A categories plus the two Day-1 arrangements that are not priced as credit (zero-cost BNPL, CPA lay-by).';

CREATE TABLE lms.ref_day_count_convention (
  code text PRIMARY KEY,
  period text NOT NULL CHECK (period IN ('year', 'month')),
  divisor_kind text NOT NULL CHECK (divisor_kind IN ('fixed_365', 'actual_year', 'fixed_30', 'actual_month')),
  statute_ref text NOT NULL
);

COMMENT ON TABLE lms.ref_day_count_convention IS
  'Regulation 40 lets the agreement choose the divisor. 30-day and actual-day are not within the 0.1% tolerance of each other; the terms version pins one.';

CREATE TABLE lms.ref_balance_code (
  code text PRIMARY KEY,
  s126_tier smallint CHECK (s126_tier BETWEEN 1 AND 3),
  in_duplum boolean NOT NULL
);

COMMENT ON TABLE lms.ref_balance_code IS
  'Sub-ledgers. Section 126 has three tiers. Section 103(5) caps section 101(1)(b) to (g) balances, not the principal sub-ledger.';

CREATE TABLE lms.ref_allocation_tier (
  tier smallint PRIMARY KEY CHECK (tier BETWEEN 1 AND 3),
  statute_text text NOT NULL
);

COMMENT ON TABLE lms.ref_allocation_tier IS
  'Section 126(3) order. There is no fourth tier and no statutory order inside tier 2.';

CREATE TABLE lms.ref_status_code (
  code text PRIMARY KEY,
  opens_in_duplum boolean NOT NULL,
  terminal boolean NOT NULL,
  description text NOT NULL
);

COMMENT ON TABLE lms.ref_status_code IS
  'LMS servicing vocabulary, not an NCA schedule. Payment arrears open an in-duplum episode even when the status is still active; opens_in_duplum covers non-payment flags an operator has recorded.';

CREATE TABLE lms.ref_status_transition (
  from_code text NOT NULL REFERENCES lms.ref_status_code (code),
  to_code text NOT NULL REFERENCES lms.ref_status_code (code),
  PRIMARY KEY (from_code, to_code)
);

CREATE TABLE lms.ref_feature_flag (
  code text PRIMARY KEY,
  description text NOT NULL
);

COMMENT ON TABLE lms.ref_feature_flag IS
  'Operational switches. The calculation engine does not read these. A price, a fee, or a cap is a terms version, not a flag.';

CREATE TABLE lms.ref_audit_event_type (
  code text PRIMARY KEY,
  category text NOT NULL CHECK (category IN ('financial', 'operational'))
);

COMMENT ON TABLE lms.ref_audit_event_type IS
  'Financial events move a balance. Operational events change LMS configuration or servicing state. Identity events are Enigma''s and are not in this list.';

-- Effective-dated statutory numbers. Overlapping spans for the same key
-- are rejected. A correction is a new row, not an update.

CREATE TABLE lms.ref_interest_cap (
  classification_code text NOT NULL REFERENCES lms.ref_credit_classification (code),
  effective_from date NOT NULL,
  effective_to date,
  cap_kind text NOT NULL CHECK (cap_kind IN ('repo_plus', 'fixed_periodic')),
  repo_margin numeric(12, 8) CHECK (repo_margin IS NULL OR (repo_margin >= 0 AND repo_margin < 1)),
  periodic_rate numeric(12, 8) CHECK (periodic_rate IS NULL OR (periodic_rate >= 0 AND periodic_rate < 1)),
  subsequent_periodic_rate numeric(12, 8) CHECK (
    subsequent_periodic_rate IS NULL OR (subsequent_periodic_rate >= 0 AND subsequent_periodic_rate < 1)
  ),
  instrument_code text NOT NULL REFERENCES lms.ref_instrument (code),
  effective_span daterange GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED,
  PRIMARY KEY (classification_code, effective_from),
  CONSTRAINT interest_cap_shape CHECK (
    (cap_kind = 'repo_plus' AND repo_margin IS NOT NULL AND periodic_rate IS NULL AND subsequent_periodic_rate IS NULL)
    OR
    (cap_kind = 'fixed_periodic' AND periodic_rate IS NOT NULL AND repo_margin IS NULL)
  ),
  CONSTRAINT interest_cap_no_overlap EXCLUDE USING gist (
    classification_code WITH =,
    effective_span WITH &&
  )
);

COMMENT ON TABLE lms.ref_interest_cap IS
  'Regulation 42 Table A as amended by GN 1080. subsequent_periodic_rate is the gazetted 3% short-term rate. Which loans are subsequent is an interpretation row, not a second cap.';

CREATE TABLE lms.ref_initiation_fee_cap (
  classification_code text NOT NULL REFERENCES lms.ref_credit_classification (code),
  effective_from date NOT NULL,
  effective_to date,
  flat_cents bigint NOT NULL CHECK (flat_cents >= 0),
  threshold_cents bigint NOT NULL CHECK (threshold_cents >= 0),
  marginal_rate numeric(12, 8) NOT NULL CHECK (marginal_rate >= 0 AND marginal_rate < 1),
  absolute_cents bigint NOT NULL CHECK (absolute_cents >= 0),
  instrument_code text NOT NULL REFERENCES lms.ref_instrument (code),
  effective_span daterange GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED,
  PRIMARY KEY (classification_code, effective_from),
  CONSTRAINT initiation_cap_no_overlap EXCLUDE USING gist (
    classification_code WITH =,
    effective_span WITH &&
  )
);

COMMENT ON TABLE lms.ref_initiation_fee_cap IS
  'Regulation 42 Table B. The 15% principal-debt limb is ref_charge_rule initiation_principal_ratio, applied as well as this table.';

CREATE TABLE lms.ref_service_fee_cap (
  effective_from date PRIMARY KEY,
  effective_to date,
  monthly_cents bigint NOT NULL CHECK (monthly_cents >= 0),
  instrument_code text NOT NULL REFERENCES lms.ref_instrument (code),
  effective_span daterange GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED,
  CONSTRAINT service_fee_no_overlap EXCLUDE USING gist (effective_span WITH &&)
);

COMMENT ON TABLE lms.ref_service_fee_cap IS
  'Regulation 44 monthly maximum. The annual maximum is this figure times 12 (regulation 44(1)); it is not stored as a second number.';

CREATE TABLE lms.ref_threshold (
  code text NOT NULL,
  effective_from date NOT NULL,
  effective_to date,
  amount_cents bigint,
  month_count integer,
  instrument_code text NOT NULL REFERENCES lms.ref_instrument (code),
  effective_span daterange GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED,
  PRIMARY KEY (code, effective_from),
  CONSTRAINT threshold_one_measure CHECK (
    (amount_cents IS NOT NULL AND month_count IS NULL)
    OR (amount_cents IS NULL AND month_count IS NOT NULL AND month_count > 0)
  ),
  CONSTRAINT threshold_no_overlap EXCLUDE USING gist (
    code WITH =,
    effective_span WITH &&
  )
);

COMMENT ON TABLE lms.ref_threshold IS
  'Section 7(1)(b) agreement-size thresholds and the regulation 39 short-term limits. Section 9 classification is derived from these, not stored on the product.';

CREATE TABLE lms.ref_charge_rule (
  code text NOT NULL,
  effective_from date NOT NULL,
  effective_to date,
  rule_kind text NOT NULL CHECK (rule_kind IN ('principal_ratio', 'percent_of_price', 'tariff_required', 'formula_unsettled')),
  ratio numeric(12, 8) CHECK (ratio IS NULL OR (ratio >= 0 AND ratio <= 1)),
  notes text NOT NULL,
  instrument_code text NOT NULL REFERENCES lms.ref_instrument (code),
  effective_span daterange GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED,
  PRIMARY KEY (code, effective_from),
  CONSTRAINT charge_rule_no_overlap EXCLUDE USING gist (
    code WITH =,
    effective_span WITH &&
  )
);

COMMENT ON TABLE lms.ref_charge_rule IS
  'Rules that are not a single rand cap. Default administration and collection costs stay unpriced until a tariff row is loaded. The engine refuses those postings rather than invent a rand amount.';

CREATE TABLE lms.ref_tariff_amount (
  code text NOT NULL,
  effective_from date NOT NULL,
  amount_cents bigint NOT NULL CHECK (amount_cents >= 0),
  instrument_code text NOT NULL REFERENCES lms.ref_instrument (code),
  PRIMARY KEY (code, effective_from)
);

COMMENT ON TABLE lms.ref_tariff_amount IS
  'Deliberately empty in Day-1. Regulation 46 and 47 point at court and debt-collector tariffs that this pass did not transcribe. A posting that needs a tariff fails closed while this table has no covering row.';

CREATE TABLE lms.ref_reference_rate (
  code text NOT NULL,
  effective_from date NOT NULL,
  effective_to date,
  annual_rate numeric(12, 8) NOT NULL CHECK (annual_rate >= 0 AND annual_rate < 1),
  confidence text NOT NULL CHECK (confidence IN ('confirmed', 'reported_unverified')),
  instrument_code text NOT NULL REFERENCES lms.ref_instrument (code),
  effective_span daterange GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED,
  PRIMARY KEY (code, effective_from),
  CONSTRAINT reference_rate_no_overlap EXCLUDE USING gist (
    code WITH =,
    effective_span WITH &&
  )
);

COMMENT ON TABLE lms.ref_reference_rate IS
  'SARB repurchase rate. The engine uses rows with confidence = confirmed only. An unverified history row must not price a variable agreement.';

CREATE TABLE lms.ref_public_holiday (
  holiday_date date PRIMARY KEY,
  name text NOT NULL,
  source text NOT NULL CHECK (source IN ('act', 'sunday_rule', 'presidential'))
);

COMMENT ON TABLE lms.ref_public_holiday IS
  'Public Holidays Act schedule plus the Sunday observance rule, and any presidential declaration inserted later. Saturday holidays are not moved.';

CREATE TABLE lms.ref_interpretation_set (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  effective_from date NOT NULL,
  effective_to date,
  status text NOT NULL CHECK (status IN ('adopted', 'superseded')),
  effective_span daterange GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED,
  CONSTRAINT one_adopted_interpretation EXCLUDE USING gist (effective_span WITH &&) WHERE (status = 'adopted')
);

COMMENT ON TABLE lms.ref_interpretation_set IS
  'A dated bundle of readings for text the Act does not settle. Agreements are not pinned to a set: the set in force on the accrual date is applied, and its id is written on the audit row. A tenant cannot adopt a more expensive reading.';

CREATE TABLE lms.ref_interpretation_choice (
  set_id uuid NOT NULL REFERENCES lms.ref_interpretation_set (id),
  question_code text NOT NULL,
  adopted_option text NOT NULL,
  alternative_option text NOT NULL,
  authority text NOT NULL CHECK (authority IN ('text', 'agreement_pin', 'tolerance', 'pending_counsel')),
  effect text NOT NULL CHECK (effect IN ('safe_ceiling', 'either_way', 'does_not_change_total')),
  notes text NOT NULL,
  PRIMARY KEY (set_id, question_code)
);

COMMENT ON TABLE lms.ref_interpretation_choice IS
  'safe_ceiling: the adopted option charges less than or equal to the alternative, so it cannot overcharge if the alternative is later held to be the law. either_way: counsel should look first.';

-- -----------------------------------------------------------------------
-- Per-organisation configuration. organisation_id is Enigma's.
-- -----------------------------------------------------------------------

CREATE TABLE lms.cfg_organisation_settings (
  organisation_id uuid PRIMARY KEY,
  timezone text NOT NULL DEFAULT 'Africa/Johannesburg' CHECK (timezone = 'Africa/Johannesburg'),
  currency character(3) NOT NULL DEFAULT 'ZAR' CHECK (currency = 'ZAR'),
  locale text NOT NULL DEFAULT 'en-ZA',
  vat_vendor boolean NOT NULL,
  actor_kind text NOT NULL CHECK (actor_kind IN ('person', 'system', 'mandate')),
  actor_enigma_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT settings_actor CHECK (
    (actor_kind = 'system' AND actor_enigma_id IS NULL)
    OR (actor_kind IN ('person', 'mandate') AND actor_enigma_id IS NOT NULL)
  )
);

COMMENT ON TABLE lms.cfg_organisation_settings IS
  'White-label and VAT facts for one Enigma organisation. No legal name and no NCR number: those are read from Enigma and snapshotted onto the agreement at origination.';

CREATE TABLE lms.cfg_brand (
  organisation_id uuid NOT NULL,
  brand_code text NOT NULL,
  display_name text NOT NULL,
  support_phone text,
  support_email text,
  logo_object_key text,
  statement_footer text,
  PRIMARY KEY (organisation_id, brand_code)
);

COMMENT ON TABLE lms.cfg_brand IS
  'Presentation only. The calculation engine must not read this table.';

CREATE TABLE lms.cfg_feature_flag (
  organisation_id uuid NOT NULL,
  flag_key text NOT NULL REFERENCES lms.ref_feature_flag (code),
  enabled boolean NOT NULL,
  effective_from timestamptz NOT NULL,
  effective_to timestamptz,
  span tstzrange GENERATED ALWAYS AS (tstzrange(effective_from, effective_to, '[)')) STORED,
  PRIMARY KEY (organisation_id, flag_key, effective_from),
  CONSTRAINT flag_no_overlap EXCLUDE USING gist (
    organisation_id WITH =,
    flag_key WITH =,
    span WITH &&
  )
);

COMMENT ON TABLE lms.cfg_feature_flag IS
  'Gates a feature for one organisation. Insert a new row to change it. Do not put a rate or a fee here.';

CREATE TABLE lms.cfg_product (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organisation_id uuid NOT NULL,
  product_code text NOT NULL,
  classification_code text NOT NULL REFERENCES lms.ref_credit_classification (code),
  enigma_enrolment_code text NOT NULL,
  UNIQUE (organisation_id, product_code)
);

COMMENT ON TABLE lms.cfg_product IS
  'Parameter container for a product Enigma has enrolled. This row does not grant enrolment. Origination checks Enigma, then loads parameters.';

CREATE TABLE lms.cfg_product_terms (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id uuid NOT NULL REFERENCES lms.cfg_product (id),
  version integer NOT NULL CHECK (version > 0),
  status text NOT NULL CHECK (status IN ('draft', 'published')),
  effective_from date NOT NULL,
  day_count_code text NOT NULL REFERENCES lms.ref_day_count_convention (code),
  intraday text NOT NULL CHECK (intraday IN ('end_of_day', 'start_of_day', 'average')),
  rate_kind text NOT NULL CHECK (rate_kind IN ('zero', 'fixed_monthly', 'fixed_annual', 'variable_rr_plus')),
  monthly_rate numeric(12, 8) CHECK (monthly_rate IS NULL OR (monthly_rate >= 0 AND monthly_rate < 1)),
  annual_rate numeric(12, 8) CHECK (annual_rate IS NULL OR (annual_rate >= 0 AND annual_rate < 1)),
  repo_margin numeric(12, 8) CHECK (repo_margin IS NULL OR (repo_margin >= 0 AND repo_margin < 1)),
  max_term_months integer CHECK (max_term_months IS NULL OR max_term_months > 0),
  max_deferred_cents bigint CHECK (max_deferred_cents IS NULL OR max_deferred_cents >= 0),
  max_principal_cents bigint CHECK (max_principal_cents IS NULL OR max_principal_cents >= 0),
  prorate_settlement_service_fee boolean NOT NULL DEFAULT false,
  published_by_enigma_id uuid,
  UNIQUE (product_id, version),
  CONSTRAINT terms_rate_shape CHECK (
    (rate_kind = 'zero' AND monthly_rate IS NULL AND annual_rate IS NULL AND repo_margin IS NULL)
    OR (rate_kind = 'fixed_monthly' AND monthly_rate IS NOT NULL AND annual_rate IS NULL AND repo_margin IS NULL)
    OR (rate_kind = 'fixed_annual' AND annual_rate IS NOT NULL AND monthly_rate IS NULL AND repo_margin IS NULL)
    OR (rate_kind = 'variable_rr_plus' AND repo_margin IS NOT NULL AND monthly_rate IS NULL AND annual_rate IS NULL)
  )
);

COMMENT ON TABLE lms.cfg_product_terms IS
  'Immutable once published. An agreement pins terms id. A later version does not reprice an existing agreement. The statutory ceiling is re-read on each accrual date and the charge is the lesser of the pin and the ceiling.';

CREATE UNIQUE INDEX cfg_product_terms_one_published_per_day
  ON lms.cfg_product_terms (product_id, effective_from)
  WHERE status = 'published';

CREATE INDEX cfg_product_terms_current
  ON lms.cfg_product_terms (product_id, effective_from DESC)
  WHERE status = 'published';

CREATE TABLE lms.cfg_fee_rule (
  terms_id uuid NOT NULL REFERENCES lms.cfg_product_terms (id) ON DELETE CASCADE,
  fee_code text NOT NULL,
  charge text NOT NULL CHECK (charge IN ('zero', 'fixed', 'statutory_formula', 'tariff')),
  amount_cents bigint CHECK (amount_cents IS NULL OR amount_cents >= 0),
  PRIMARY KEY (terms_id, fee_code),
  CONSTRAINT fee_amount_matches_charge CHECK (
    (charge = 'fixed' AND amount_cents IS NOT NULL)
    OR (charge <> 'fixed' AND (amount_cents IS NULL OR amount_cents = 0))
  )
);

COMMENT ON TABLE lms.cfg_fee_rule IS
  'A missing fee row means the fee is not charged. It does not mean "charge the statutory maximum".';

CREATE TABLE lms.cfg_instrument (
  terms_id uuid NOT NULL REFERENCES lms.cfg_product_terms (id) ON DELETE CASCADE,
  instrument_code text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('credit', 'security_deposit', 'cpa_layby')),
  setoff_requires_mandate boolean NOT NULL DEFAULT false,
  PRIMARY KEY (terms_id, instrument_code),
  CONSTRAINT deposit_needs_mandate CHECK (kind <> 'security_deposit' OR setoff_requires_mandate)
);

COMMENT ON TABLE lms.cfg_instrument IS
  'A lay-by security product is a short-term credit instrument plus a zero-interest deposit. The deposit is not a CPA lay-by and cannot take the 1% cancellation penalty.';

CREATE TABLE lms.cfg_cache_generation (
  id boolean PRIMARY KEY DEFAULT true CHECK (id),
  generation bigint NOT NULL DEFAULT 0
);

INSERT INTO lms.cfg_cache_generation (id, generation) VALUES (true, 0);

COMMENT ON TABLE lms.cfg_cache_generation IS
  'Incremented when configuration changes. Process caches of caps and holidays key on this and must not cache a terms version beyond the request that pinned it.';

-- -----------------------------------------------------------------------
-- Audit. Append-only, hashed per organisation, partitioned by UTC month.
-- -----------------------------------------------------------------------

CREATE TABLE lms.audit_event (
  occurred_at timestamptz NOT NULL,
  event_id uuid NOT NULL DEFAULT gen_random_uuid(),
  organisation_id uuid NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  event_type text NOT NULL REFERENCES lms.ref_audit_event_type (code),
  agreement_id uuid,
  enigma_person_id uuid,
  actor_kind text NOT NULL CHECK (actor_kind IN ('person', 'system', 'mandate')),
  actor_enigma_id uuid,
  mandate_id uuid,
  correlation_id uuid NOT NULL,
  causation_id uuid,
  terms_version_id uuid,
  interpretation_set_id uuid,
  amount_cents bigint CHECK (amount_cents IS NULL OR amount_cents >= 0),
  currency character(3) NOT NULL DEFAULT 'ZAR' CHECK (currency = 'ZAR'),
  balance_code text REFERENCES lms.ref_balance_code (code),
  idempotency_key text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
  previous_hash bytea,
  row_hash bytea,
  PRIMARY KEY (occurred_at, event_id),
  CONSTRAINT audit_actor CHECK (
    (actor_kind = 'system' AND actor_enigma_id IS NULL)
    OR (actor_kind IN ('person', 'mandate') AND actor_enigma_id IS NOT NULL)
  )
) PARTITION BY RANGE (occurred_at);

COMMENT ON TABLE lms.audit_event IS
  'Financial and LMS operational events. No identity edits, no credentials, no consumer id numbers. Regulation 56: keep credit-agreement records for three years from termination, so partitions are not dropped on a rolling three years from the event date.';

CREATE TABLE lms.audit_chain_head (
  organisation_id uuid PRIMARY KEY,
  last_event_id uuid NOT NULL,
  last_occurred_at timestamptz NOT NULL,
  last_hash bytea NOT NULL
);

CREATE TABLE lms.audit_idempotency (
  organisation_id uuid NOT NULL,
  idempotency_key text NOT NULL,
  event_id uuid NOT NULL,
  occurred_at timestamptz NOT NULL,
  PRIMARY KEY (organisation_id, idempotency_key)
);

COMMENT ON TABLE lms.audit_idempotency IS
  'A unique key cannot be declared on the partitioned audit table without the partition column. This side table is the idempotency constraint.';

CREATE INDEX audit_event_org_time
  ON lms.audit_event (organisation_id, occurred_at DESC);

CREATE INDEX audit_event_agreement_time
  ON lms.audit_event (agreement_id, occurred_at DESC)
  WHERE agreement_id IS NOT NULL;

CREATE INDEX audit_event_correlation
  ON lms.audit_event (organisation_id, correlation_id);

CREATE FUNCTION lms.ensure_audit_partition(p_month date) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  start_date date := date_trunc('month', p_month)::date;
  end_date date := (start_date + interval '1 month')::date;
  start_ts timestamptz := start_date::timestamp AT TIME ZONE 'UTC';
  end_ts timestamptz := end_date::timestamp AT TIME ZONE 'UTC';
  part_name text := format('audit_event_%s', to_char(start_date, 'YYYY_MM'));
BEGIN
  EXECUTE format(
    'CREATE TABLE IF NOT EXISTS lms.%I PARTITION OF lms.audit_event FOR VALUES FROM (%L) TO (%L)',
    part_name, start_ts, end_ts
  );
END;
$$;

SELECT lms.ensure_audit_partition(month_start::date)
FROM generate_series('2026-10-01'::date, '2032-12-01'::date, interval '1 month') AS month_start;

CREATE FUNCTION lms.seal_audit_event() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = lms, public, pg_temp
AS $$
DECLARE
  prev bytea;
  category text;
  canonical text;
BEGIN
  SELECT ref.category INTO category
  FROM lms.ref_audit_event_type AS ref
  WHERE ref.code = NEW.event_type;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'unknown audit event type %', NEW.event_type USING ERRCODE = '23503';
  END IF;
  IF category = 'financial' AND NEW.amount_cents IS NULL THEN
    RAISE EXCEPTION 'financial audit event % requires amount_cents', NEW.event_type USING ERRCODE = '23514';
  END IF;
  IF category = 'operational' AND NEW.amount_cents IS NOT NULL THEN
    RAISE EXCEPTION 'operational audit event % must not carry amount_cents', NEW.event_type USING ERRCODE = '23514';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.organisation_id::text, 0));

  SELECT last_hash INTO prev
  FROM lms.audit_chain_head
  WHERE organisation_id = NEW.organisation_id
  FOR UPDATE;

  NEW.previous_hash := prev;
  canonical := concat_ws(
    '|',
    NEW.organisation_id::text,
    NEW.event_id::text,
    COALESCE(encode(prev, 'hex'), ''),
    NEW.event_type,
    NEW.occurred_at::text,
    COALESCE(NEW.amount_cents::text, ''),
    COALESCE(NEW.balance_code, ''),
    NEW.payload::text
  );
  NEW.row_hash := public.digest(convert_to(canonical, 'UTF8'), 'sha256');

  INSERT INTO lms.audit_chain_head (organisation_id, last_event_id, last_occurred_at, last_hash)
  VALUES (NEW.organisation_id, NEW.event_id, NEW.occurred_at, NEW.row_hash)
  ON CONFLICT (organisation_id) DO UPDATE
    SET last_event_id = EXCLUDED.last_event_id,
        last_occurred_at = EXCLUDED.last_occurred_at,
        last_hash = EXCLUDED.last_hash;

  IF NEW.idempotency_key IS NOT NULL THEN
    INSERT INTO lms.audit_idempotency (organisation_id, idempotency_key, event_id, occurred_at)
    VALUES (NEW.organisation_id, NEW.idempotency_key, NEW.event_id, NEW.occurred_at);
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER seal_audit_event
  BEFORE INSERT ON lms.audit_event
  FOR EACH ROW EXECUTE FUNCTION lms.seal_audit_event();

CREATE FUNCTION lms.reject_audit_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_event is append-only' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER reject_audit_update
  BEFORE UPDATE OR DELETE ON lms.audit_event
  FOR EACH ROW EXECUTE FUNCTION lms.reject_audit_mutation();

CREATE FUNCTION lms.published_terms_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'published terms cannot be deleted' USING ERRCODE = '55000';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'published' THEN
    RAISE EXCEPTION 'published terms cannot be updated' USING ERRCODE = '55000';
  END IF;
  IF NEW.status NOT IN ('draft', 'published') THEN
    RAISE EXCEPTION 'unknown terms status %', NEW.status USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER published_terms_immutable
  BEFORE UPDATE OR DELETE ON lms.cfg_product_terms
  FOR EACH ROW EXECUTE FUNCTION lms.published_terms_immutable();

CREATE FUNCTION lms.fee_rules_follow_terms() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  parent_status text;
  parent uuid;
BEGIN
  parent := COALESCE(NEW.terms_id, OLD.terms_id);
  SELECT status INTO parent_status FROM lms.cfg_product_terms WHERE id = parent;
  IF parent_status = 'published' THEN
    RAISE EXCEPTION 'fee rules of published terms are frozen' USING ERRCODE = '55000';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER fee_rules_follow_terms
  BEFORE INSERT OR UPDATE OR DELETE ON lms.cfg_fee_rule
  FOR EACH ROW EXECUTE FUNCTION lms.fee_rules_follow_terms();

CREATE FUNCTION lms.bump_cache_generation() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = lms, pg_temp
AS $$
BEGIN
  UPDATE lms.cfg_cache_generation SET generation = generation + 1 WHERE id;
  RETURN NULL;
END;
$$;

CREATE TRIGGER bump_cache_on_terms
  AFTER INSERT OR UPDATE OR DELETE ON lms.cfg_product_terms
  FOR EACH STATEMENT EXECUTE FUNCTION lms.bump_cache_generation();

CREATE TRIGGER bump_cache_on_flags
  AFTER INSERT OR UPDATE OR DELETE ON lms.cfg_feature_flag
  FOR EACH STATEMENT EXECUTE FUNCTION lms.bump_cache_generation();

CREATE FUNCTION lms.is_business_day(p_day date) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXTRACT(DOW FROM p_day) NOT IN (0, 6)
     AND NOT EXISTS (
       SELECT 1 FROM lms.ref_public_holiday AS holiday
       WHERE holiday.holiday_date = p_day
     );
$$;

COMMENT ON FUNCTION lms.is_business_day(date) IS
  'Saturday, Sunday, and ref_public_holiday. Matches lms_config.calendar.is_business_day. Section 2(5) counting is add_business_days in Python; keep the two together.';

-- Row level security. The runtime role is lms_app. Reference tables are
-- world-readable inside the schema and are not tenant-scoped. FORCE ROW
-- LEVEL SECURITY so the table owner, including SECURITY DEFINER triggers,
-- is held to the same organisation_id session variable.

GRANT USAGE ON SCHEMA lms TO lms_app, lms_reader;

DO $$
DECLARE
  tenant text;
BEGIN
  FOREACH tenant IN ARRAY ARRAY[
    'cfg_organisation_settings',
    'cfg_brand',
    'cfg_feature_flag',
    'cfg_product',
    'audit_event',
    'audit_chain_head',
    'audit_idempotency'
  ]
  LOOP
    EXECUTE format('ALTER TABLE lms.%I ENABLE ROW LEVEL SECURITY', tenant);
    EXECUTE format('ALTER TABLE lms.%I FORCE ROW LEVEL SECURITY', tenant);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON lms.%I USING (organisation_id = current_setting(''lms.organisation_id'', true)::uuid) WITH CHECK (organisation_id = current_setting(''lms.organisation_id'', true)::uuid)',
      tenant
    );
  END LOOP;
END $$;

-- Terms, fees, and instruments are reached through the product. Their
-- tenant scope is the parent product's organisation. A direct policy on
-- the child uses a lookup the owner can see because ref-style reads of
-- cfg_product are themselves tenant-filtered: the lookup returns a row
-- only for the current organisation, which is what we want.

ALTER TABLE lms.cfg_product_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms.cfg_product_terms FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON lms.cfg_product_terms
  USING (
    EXISTS (
      SELECT 1 FROM lms.cfg_product AS product
      WHERE product.id = product_id
        AND product.organisation_id = current_setting('lms.organisation_id', true)::uuid
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM lms.cfg_product AS product
      WHERE product.id = product_id
        AND product.organisation_id = current_setting('lms.organisation_id', true)::uuid
    )
  );

ALTER TABLE lms.cfg_fee_rule ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms.cfg_fee_rule FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON lms.cfg_fee_rule
  USING (
    EXISTS (
      SELECT 1
      FROM lms.cfg_product_terms AS terms
      JOIN lms.cfg_product AS product ON product.id = terms.product_id
      WHERE terms.id = terms_id
        AND product.organisation_id = current_setting('lms.organisation_id', true)::uuid
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM lms.cfg_product_terms AS terms
      JOIN lms.cfg_product AS product ON product.id = terms.product_id
      WHERE terms.id = terms_id
        AND product.organisation_id = current_setting('lms.organisation_id', true)::uuid
    )
  );

ALTER TABLE lms.cfg_instrument ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms.cfg_instrument FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON lms.cfg_instrument
  USING (
    EXISTS (
      SELECT 1
      FROM lms.cfg_product_terms AS terms
      JOIN lms.cfg_product AS product ON product.id = terms.product_id
      WHERE terms.id = terms_id
        AND product.organisation_id = current_setting('lms.organisation_id', true)::uuid
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM lms.cfg_product_terms AS terms
      JOIN lms.cfg_product AS product ON product.id = terms.product_id
      WHERE terms.id = terms_id
        AND product.organisation_id = current_setting('lms.organisation_id', true)::uuid
    )
  );

GRANT SELECT ON ALL TABLES IN SCHEMA lms TO lms_app, lms_reader;
GRANT INSERT, UPDATE, DELETE ON
  lms.cfg_organisation_settings,
  lms.cfg_brand,
  lms.cfg_feature_flag,
  lms.cfg_product,
  lms.cfg_product_terms,
  lms.cfg_fee_rule,
  lms.cfg_instrument
TO lms_app;
GRANT INSERT ON lms.audit_event TO lms_app;

-- Published-terms immutability is the trigger. Draft rows may be deleted
-- by the app. Audit tables are insert-only for the app; the seal trigger
-- writes the chain head and the idempotency row as the table owner, still
-- under the tenant policy.
REVOKE UPDATE, DELETE, TRUNCATE ON lms.audit_event FROM lms_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
  lms.audit_chain_head,
  lms.audit_idempotency
FROM lms_app;
