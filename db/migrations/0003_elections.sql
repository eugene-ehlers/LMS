-- Elections named in docs/LOCKED_DECISIONS.md decision 19, plus the
-- day-count and campaign price the engine reads with them.
-- Organisation row, optional product override. Null is unset.
-- Unset fails closed in the read path. This file does not pick a value.
-- Decision 10 names "none" as the substantive default for initiation
-- interest. Decision 19 says an unset election fails closed. The column
-- is therefore nullable: storing the word none is the provider's choice
-- of that default, and a null row does not silently become none.

SET TIME ZONE 'UTC';

ALTER TABLE lms.cfg_organisation_settings
  ALTER COLUMN interest_on_deferred_initiation DROP NOT NULL,
  ALTER COLUMN interest_on_deferred_initiation DROP DEFAULT;

ALTER TABLE lms.cfg_organisation_settings
  ADD COLUMN day_count_code text
    CHECK (day_count_code IS NULL OR day_count_code IN ('actual_actual', 'thirty_360')),
  ADD COLUMN base_rate numeric(12, 8)
    CHECK (base_rate IS NULL OR (base_rate >= 0 AND base_rate < 1)),
  ADD COLUMN discount_rate numeric(12, 8)
    CHECK (discount_rate IS NULL OR (discount_rate >= 0 AND discount_rate < 1)),
  ADD COLUMN vat_on_rand_maxima text
    CHECK (vat_on_rand_maxima IS NULL OR vat_on_rand_maxima IN ('exclusive', 'inclusive')),
  ADD COLUMN late_disbursement text
    CHECK (late_disbursement IS NULL OR late_disbursement IN ('adjust_instalment', 'keep_instalment')),
  ADD COLUMN partial_prepayment text
    CHECK (partial_prepayment IS NULL OR partial_prepayment IN ('shorten_term', 'drop_instalment')),
  ADD CONSTRAINT organisation_campaign_pair CHECK (
    (base_rate IS NULL AND discount_rate IS NULL)
    OR (
      base_rate IS NOT NULL
      AND discount_rate IS NOT NULL
      AND discount_rate <= base_rate
    )
  );

COMMENT ON COLUMN lms.cfg_organisation_settings.day_count_code IS
  'Decision 5. actual_actual or thirty_360. Null inherits nothing: the read fails closed if the product does not override it. A 360-day year is not required for Day-1; the code stays selectable.';

COMMENT ON COLUMN lms.cfg_organisation_settings.base_rate IS
  'Decision 3. Organisation campaign base, in the product rate unit when the product does not set its own. Null with a null discount is unset.';

COMMENT ON COLUMN lms.cfg_organisation_settings.discount_rate IS
  'Decision 3. Deducted from base_rate. A performing rate of zero is a discount equal to the base. Null is unset, not a zero discount.';

COMMENT ON COLUMN lms.cfg_organisation_settings.vat_on_rand_maxima IS
  'Decisions 9 and 19. exclusive or inclusive for the R60, R165 and R1 050 maxima. Decision 9 names exclusive as the treatment; decision 19 says an unset election fails closed, so this column has no default.';

COMMENT ON COLUMN lms.cfg_organisation_settings.late_disbursement IS
  'Decisions 13 and 19. adjust_instalment or keep_instalment when disbursement is later than the quote date. Null fails closed.';

COMMENT ON COLUMN lms.cfg_organisation_settings.partial_prepayment IS
  'Decisions 13 and 19. shorten_term or drop_instalment. Null fails closed. shorten_term keeps the contractual instalment, which is the preference decision 13 also states. The preference is not a silent default.';

COMMENT ON COLUMN lms.cfg_organisation_settings.interest_on_deferred_initiation IS
  'Decisions 10 and 19. none or permitted. Null fails closed. Storing none is how the provider takes the decision 10 default.';

ALTER TABLE lms.cfg_product_terms
  ALTER COLUMN day_count_code DROP NOT NULL,
  ALTER COLUMN discount_rate DROP NOT NULL,
  ALTER COLUMN discount_rate DROP DEFAULT;

ALTER TABLE lms.cfg_product_terms
  ADD COLUMN vat_on_rand_maxima text
    CHECK (vat_on_rand_maxima IS NULL OR vat_on_rand_maxima IN ('exclusive', 'inclusive')),
  ADD COLUMN late_disbursement text
    CHECK (late_disbursement IS NULL OR late_disbursement IN ('adjust_instalment', 'keep_instalment')),
  ADD COLUMN partial_prepayment text
    CHECK (partial_prepayment IS NULL OR partial_prepayment IN ('shorten_term', 'drop_instalment')),
  ADD COLUMN initiation_capitalised boolean NOT NULL DEFAULT false,
  ADD COLUMN payment_frequency text;

COMMENT ON COLUMN lms.cfg_product_terms.day_count_code IS
  'Decision 5. Null inherits the organisation. It does not mean actual/actual.';

COMMENT ON COLUMN lms.cfg_product_terms.vat_on_rand_maxima IS
  'Decision 19 product override. Null inherits the organisation.';

COMMENT ON COLUMN lms.cfg_product_terms.late_disbursement IS
  'Decision 19 product override. Null inherits the organisation.';

COMMENT ON COLUMN lms.cfg_product_terms.partial_prepayment IS
  'Decision 19 product override. Null inherits the organisation.';

COMMENT ON COLUMN lms.cfg_product_terms.initiation_capitalised IS
  'Decision 2. Short-term and unsecured default to non-capitalised. Only a section 102 agreement type may set this true. Day-1 classifications are not those types.';

COMMENT ON COLUMN lms.cfg_product_terms.payment_frequency IS
  'Decision 14 vocabulary. Null is not a failure: the lock requires the six frequencies to be available and does not say a missing product frequency fails closed.';

ALTER TABLE lms.cfg_product_terms DROP CONSTRAINT terms_rate_shape;
ALTER TABLE lms.cfg_product_terms DROP CONSTRAINT campaign_matches_effective;

ALTER TABLE lms.cfg_product_terms
  ADD CONSTRAINT terms_rate_shape CHECK (
    (rate_kind = 'zero' AND monthly_rate IS NULL AND annual_rate IS NULL AND repo_margin IS NULL)
    OR (rate_kind = 'fixed_monthly' AND annual_rate IS NULL AND repo_margin IS NULL)
    OR (rate_kind = 'fixed_annual' AND monthly_rate IS NULL AND repo_margin IS NULL)
    OR (rate_kind = 'variable_rr_plus' AND monthly_rate IS NULL AND annual_rate IS NULL)
  );

-- A null base and a null discount inherit the organisation pair.
-- A set base stores the campaign on this version, and the effective
-- column must equal base minus discount so the two cannot drift.
ALTER TABLE lms.cfg_product_terms
  ADD CONSTRAINT campaign_matches_effective CHECK (
    (
      base_rate IS NULL
      AND discount_rate IS NULL
      AND monthly_rate IS NULL
      AND annual_rate IS NULL
      AND repo_margin IS NULL
    )
    OR (
      rate_kind = 'zero'
      AND base_rate IS NULL
      AND (discount_rate IS NULL OR discount_rate = 0)
      AND monthly_rate IS NULL
      AND annual_rate IS NULL
      AND repo_margin IS NULL
    )
    OR (
      rate_kind = 'fixed_monthly'
      AND base_rate IS NOT NULL
      AND discount_rate IS NOT NULL
      AND discount_rate <= base_rate
      AND monthly_rate = base_rate - discount_rate
    )
    OR (
      rate_kind = 'fixed_annual'
      AND base_rate IS NOT NULL
      AND discount_rate IS NOT NULL
      AND discount_rate <= base_rate
      AND annual_rate = base_rate - discount_rate
    )
    OR (
      rate_kind = 'variable_rr_plus'
      AND base_rate IS NOT NULL
      AND discount_rate IS NOT NULL
      AND discount_rate <= base_rate
      AND repo_margin = base_rate - discount_rate
    )
  );

CREATE TABLE lms.ref_payment_frequency (
  code text PRIMARY KEY
);

INSERT INTO lms.ref_payment_frequency (code) VALUES
  ('weekly'),
  ('fortnightly'),
  ('monthly'),
  ('quarterly'),
  ('bi_annual'),
  ('annual');

COMMENT ON TABLE lms.ref_payment_frequency IS
  'Decision 14. weekly, fortnightly, monthly, quarterly, bi-annual, annual. The anchor day and the number of periods in a year are not in the lock.';

ALTER TABLE lms.cfg_product_terms
  ADD CONSTRAINT terms_payment_frequency_fk
  FOREIGN KEY (payment_frequency) REFERENCES lms.ref_payment_frequency (code);

GRANT SELECT ON lms.ref_payment_frequency TO lms_app, lms_reader;

-- Decision 13. Subsequent short-term loans are counted per organisation
-- and per calendar year. The earlier lifetime count is not the rule.
UPDATE lms.ref_interpretation_choice
SET adopted_option = 'per_organisation_and_calendar_year',
    alternative_option = 'lifetime_with_organisation',
    authority = 'text',
    effect = 'locked',
    notes = 'Decision 13. A subsequent short-term loan is counted per credit-provider organisation and per calendar year. A quote that does not disburse does not count.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'short_term_ordinal';

-- Decision 1. Same-day events at 00:00 keep the order the system recognised
-- them. The seal assigns a per-organisation sequence. Callers do not pick it.
ALTER TABLE lms.audit_chain_head
  ADD COLUMN last_sequence bigint NOT NULL DEFAULT 0;

ALTER TABLE lms.audit_event
  ADD COLUMN recognition_sequence bigint;

COMMENT ON COLUMN lms.audit_event.recognition_sequence IS
  'Decision 1. Monotonic per organisation, assigned when the event is sealed. Same value date sorts by this sequence.';

CREATE OR REPLACE FUNCTION lms.seal_audit_event() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = lms, public, pg_temp
AS $$
DECLARE
  prev bytea;
  seq bigint;
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

  SELECT last_hash, last_sequence INTO prev, seq
  FROM lms.audit_chain_head
  WHERE organisation_id = NEW.organisation_id
  FOR UPDATE;

  IF NOT FOUND THEN
    seq := 1;
    prev := NULL;
  ELSE
    seq := seq + 1;
  END IF;

  NEW.recognition_sequence := seq;
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
    seq::text,
    NEW.payload::text
  );
  NEW.row_hash := public.digest(convert_to(canonical, 'UTF8'), 'sha256');

  INSERT INTO lms.audit_chain_head (
    organisation_id, last_event_id, last_occurred_at, last_hash, last_sequence
  )
  VALUES (NEW.organisation_id, NEW.event_id, NEW.occurred_at, NEW.row_hash, seq)
  ON CONFLICT (organisation_id) DO UPDATE
    SET last_event_id = EXCLUDED.last_event_id,
        last_occurred_at = EXCLUDED.last_occurred_at,
        last_hash = EXCLUDED.last_hash,
        last_sequence = EXCLUDED.last_sequence;

  IF NEW.idempotency_key IS NOT NULL THEN
    INSERT INTO lms.audit_idempotency (organisation_id, idempotency_key, event_id, occurred_at)
    VALUES (NEW.organisation_id, NEW.idempotency_key, NEW.event_id, NEW.occurred_at);
  END IF;

  RETURN NEW;
END;
$$;
