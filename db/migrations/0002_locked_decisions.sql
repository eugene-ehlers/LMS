-- Configuration required by docs/LOCKED_DECISIONS.md.
-- That document wins where this schema and 0001 differ.
-- Apply after 0001. Safe on a database that already has the 0001 seed:
-- interpretation rows are updated here, and a fresh install's seed inserts
-- the same text after this file has widened the effect check.

SET TIME ZONE 'UTC';

-- Decision 5. actual/actual and 30/360 are the provider's choice. The
-- regulation 40 rows from 0001 stay, so an old pin can still be read.
-- 30/360 can differ from the prescribed divisor by more than 0.1% a year.
-- The agreement pins the provider's choice anyway.

DO $$
DECLARE
  cons text;
BEGIN
  FOR cons IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'lms.ref_day_count_convention'::regclass
      AND contype = 'c'
      AND (
        pg_get_constraintdef(oid) LIKE '%period%'
        OR pg_get_constraintdef(oid) LIKE '%divisor_kind%'
      )
  LOOP
    EXECUTE format('ALTER TABLE lms.ref_day_count_convention DROP CONSTRAINT %I', cons);
  END LOOP;
END $$;

ALTER TABLE lms.ref_day_count_convention
  ADD CONSTRAINT ref_day_count_period_check
  CHECK (period IN ('year', 'month', 'either'));

ALTER TABLE lms.ref_day_count_convention
  ADD CONSTRAINT ref_day_count_divisor_check
  CHECK (divisor_kind IN (
    'fixed_365', 'actual_year', 'fixed_30', 'actual_month', 'actual_actual', 'thirty_360'
  ));

INSERT INTO lms.ref_day_count_convention (code, period, divisor_kind, statute_ref) VALUES
  (
    'actual_actual',
    'either',
    'actual_actual',
    'Locked decision 5. Actual days in the month and actual days in the year. Recommended for a new product.'
  ),
  (
    'thirty_360',
    'either',
    'thirty_360',
    'Locked decision 5. 30-day month and 360-day year. Selectable. It can differ from regulation 40 by more than 0.1% a year.'
  )
ON CONFLICT (code) DO NOTHING;

-- Decision 1. The value time is 00:00 on the Johannesburg calendar day.
-- end_of_day and average are no longer publishable.

DO $$
DECLARE
  cons text;
BEGIN
  SELECT conname INTO cons
  FROM pg_constraint
  WHERE conrelid = 'lms.cfg_product_terms'::regclass
    AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%intraday%';
  IF cons IS NOT NULL THEN
    EXECUTE format('ALTER TABLE lms.cfg_product_terms DROP CONSTRAINT %I', cons);
  END IF;
END $$;

ALTER TABLE lms.cfg_product_terms
  ALTER COLUMN intraday SET DEFAULT 'start_of_day';

ALTER TABLE lms.cfg_product_terms
  ADD CONSTRAINT cfg_product_terms_intraday_check
  CHECK (intraday = 'start_of_day');

-- Decision 9. The settlement month is a full monthly service fee. The
-- column remains so an old insert still parses, and it cannot be turned on.

ALTER TABLE lms.cfg_product_terms
  ADD CONSTRAINT settlement_month_service_fee_is_full
  CHECK (prorate_settlement_service_fee = false);

COMMENT ON COLUMN lms.cfg_product_terms.prorate_settlement_service_fee IS
  'Locked decision 9: the settlement month is the full monthly fee, subject to the R60 cap. This column cannot be true.';

-- Decision 6. Leniency and the full-payment threshold. Null means not
-- configured. The engine does not substitute 4, 5, or 95. A product null
-- inherits the organisation. Zero leniency is a real setting: flag on the
-- due date once that day's receipts are in.

ALTER TABLE lms.cfg_organisation_settings
  ADD COLUMN leniency_days integer
    CHECK (leniency_days IS NULL OR leniency_days >= 0),
  ADD COLUMN full_payment_threshold_percent numeric(6, 3)
    CHECK (
      full_payment_threshold_percent IS NULL
      OR (
        full_payment_threshold_percent > 0
        AND full_payment_threshold_percent <= 100
      )
    ),
  ADD COLUMN interest_on_deferred_initiation text NOT NULL DEFAULT 'none'
    CHECK (interest_on_deferred_initiation IN ('none', 'permitted')),
  ADD COLUMN repo_rate_fall text
    CHECK (
      repo_rate_fall IS NULL
      OR repo_rate_fall IN ('contract_rate', 'lower_of_contract_and_cap')
    );

COMMENT ON COLUMN lms.cfg_organisation_settings.leniency_days IS
  'Locked decision 6. Calendar days after the contractual due date before default is flagged. Null is not configured. The examples 4 and 5 are not a default.';

COMMENT ON COLUMN lms.cfg_organisation_settings.full_payment_threshold_percent IS
  'Locked decision 6. Percent of the instalment that counts as full. 95 means 95 percent. Null is not configured.';

COMMENT ON COLUMN lms.cfg_organisation_settings.interest_on_deferred_initiation IS
  'Locked decision 10. Default none: a deferred initiation fee earns no interest. permitted is the alternative the provider may choose.';

COMMENT ON COLUMN lms.cfg_organisation_settings.repo_rate_fall IS
  'Locked decision 11. contract_rate keeps the contract rate when the repo rate falls. lower_of_contract_and_cap accrues at the lower figure and the s104 notice is issued. Null fails closed. There is no platform default.';

ALTER TABLE lms.cfg_product_terms
  ADD COLUMN leniency_days integer
    CHECK (leniency_days IS NULL OR leniency_days >= 0),
  ADD COLUMN full_payment_threshold_percent numeric(6, 3)
    CHECK (
      full_payment_threshold_percent IS NULL
      OR (
        full_payment_threshold_percent > 0
        AND full_payment_threshold_percent <= 100
      )
    ),
  ADD COLUMN interest_on_deferred_initiation text
    CHECK (
      interest_on_deferred_initiation IS NULL
      OR interest_on_deferred_initiation IN ('none', 'permitted')
    ),
  ADD COLUMN repo_rate_fall text
    CHECK (
      repo_rate_fall IS NULL
      OR repo_rate_fall IN ('contract_rate', 'lower_of_contract_and_cap')
    );

COMMENT ON COLUMN lms.cfg_product_terms.leniency_days IS
  'Product override of the organisation leniency. Null inherits. It does not mean zero days.';

COMMENT ON COLUMN lms.cfg_product_terms.full_payment_threshold_percent IS
  'Product override of the organisation full-payment threshold. Null inherits. It does not mean 100 percent.';

-- Decision 3. Campaign price is a base rate minus a discount. The
-- effective contractual column (monthly_rate, annual_rate, or repo_margin)
-- must equal base minus discount, so the two cannot drift. A discount of
-- zero is a campaign with nothing off. A discount equal to the base is a
-- zero rate and must still calculate. When the discount falls away the
-- rate charged is the base, so the base itself has to be within the
-- statutory cap at origination.

ALTER TABLE lms.cfg_product_terms
  ADD COLUMN base_rate numeric(12, 8)
    CHECK (base_rate IS NULL OR (base_rate >= 0 AND base_rate < 1)),
  ADD COLUMN discount_rate numeric(12, 8) NOT NULL DEFAULT 0
    CHECK (discount_rate >= 0 AND discount_rate < 1);

ALTER TABLE lms.cfg_product_terms
  ADD CONSTRAINT campaign_matches_effective CHECK (
    (
      rate_kind = 'zero'
      AND base_rate IS NULL
      AND discount_rate = 0
    )
    OR (
      rate_kind = 'fixed_monthly'
      AND base_rate IS NOT NULL
      AND discount_rate <= base_rate
      AND monthly_rate = base_rate - discount_rate
    )
    OR (
      rate_kind = 'fixed_annual'
      AND base_rate IS NOT NULL
      AND discount_rate <= base_rate
      AND annual_rate = base_rate - discount_rate
    )
    OR (
      rate_kind = 'variable_rr_plus'
      AND base_rate IS NOT NULL
      AND discount_rate <= base_rate
      AND repo_margin = base_rate - discount_rate
    )
  );

COMMENT ON COLUMN lms.cfg_product_terms.base_rate IS
  'Locked decision 3. Rate before the campaign discount, in the unit of rate_kind (monthly fraction, annual fraction, or repo margin). Charged when the discount falls away on default. Not above the contractual rate, because it is that rate once the discount is gone.';

COMMENT ON COLUMN lms.cfg_product_terms.discount_rate IS
  'Locked decision 3. Campaign discount deducted from base_rate. Zero means no campaign. Equal to the base means the performing rate is zero.';

COMMENT ON TABLE lms.cfg_product_terms IS
  'Immutable once published. An agreement pins terms id. A later version does not reprice an existing agreement. See docs/LOCKED_DECISIONS.md for the day boundary, the default test, campaign rates, and whether a later fall in the repo rate reduces the accrual.';

-- The interpretation effect list gains the value used when a locked
-- decision has closed the question.

DO $$
DECLARE
  cons text;
BEGIN
  SELECT conname INTO cons
  FROM pg_constraint
  WHERE conrelid = 'lms.ref_interpretation_choice'::regclass
    AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%effect%';
  IF cons IS NOT NULL THEN
    EXECUTE format('ALTER TABLE lms.ref_interpretation_choice DROP CONSTRAINT %I', cons);
  END IF;
END $$;

ALTER TABLE lms.ref_interpretation_choice
  ADD CONSTRAINT ref_interpretation_effect_check
  CHECK (effect IN ('safe_ceiling', 'either_way', 'does_not_change_total', 'locked'));

UPDATE lms.ref_interpretation_choice
SET adopted_option = 'calendar_day_at_0000',
    alternative_option = 'end_of_day',
    authority = 'text',
    effect = 'locked',
    notes = 'Locked decision 1. Start of the day is 00:00 Africa/Johannesburg. A loan, settlement, or deposit at any time on a calendar day is value-dated 00:00 that day, before that day''s interest.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'intraday_balance';

UPDATE lms.ref_interpretation_choice
SET adopted_option = 'due_plus_leniency_and_threshold',
    alternative_option = 'immediate_arrears',
    authority = 'text',
    effect = 'locked',
    notes = 'Locked decision 6. One test for in duplum and for collections. Flag only on the contractual due date plus the configured leniency days, and only if receipts are below the configured percent of the instalment. Leniency does not pause interest.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'default_trigger';

UPDATE lms.ref_interpretation_choice
SET adopted_option = 'opening_period_disbursement_to_first_due',
    alternative_option = 'calendar_month_of_conclusion',
    authority = 'text',
    effect = 'locked',
    notes = 'Locked decision 9, citing regulation 44(4) and Micro Finance South Africa v National Credit Regulator. Pro-rata only from disbursement to the first payment due. Every later month, including the settlement month, is the full monthly fee, capped at R60.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'inception_service_day';

UPDATE lms.ref_interpretation_choice
SET adopted_option = 'full_month',
    alternative_option = 'pro_rata',
    authority = 'text',
    effect = 'locked',
    notes = 'Locked decision 9. The settlement month is a full monthly service fee, subject to the R60 cap. A product cannot prorate it.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'settlement_month_service_fee';

UPDATE lms.ref_interpretation_choice
SET adopted_option = 'stored_per_organisation_or_product',
    alternative_option = 'platform_default',
    authority = 'text',
    effect = 'locked',
    notes = 'Locked decision 11. When the repo rate falls the provider has already chosen contract_rate or lower_of_contract_and_cap. There is no platform default. A null choice fails closed. Option B also requires the section 104 notice.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'cap_test_date';

UPDATE lms.ref_interpretation_choice
SET adopted_option = 'cumulative',
    alternative_option = 'floating',
    authority = 'text',
    effect = 'locked',
    notes = 'Locked decision 7, aligned with section 103(5) and Nedbank Ltd v National Credit Regulator [2011] ZASCA 35. The base is unpaid principal at the first default, including pre-default capitalised initiation. Payments do not reset the counter. Post-default accruals stay charges.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'in_duplum_headroom';

UPDATE lms.ref_interpretation_choice
SET adopted_option = 'pre_default_initiation_joins_principal',
    alternative_option = 'initiation_stays_a_fee',
    authority = 'text',
    effect = 'locked',
    notes = 'Locked decisions 2 and 7. A capitalised initiation fee is part of principal. If it is not capitalised it stays a due fee under section 126. Post-default interest and fees remain charges for section 103(5) and section 126 even when a statement shows them as capitalised.'
WHERE set_id = '00000000-0000-4000-8000-0000000000a1'
  AND question_code = 'capitalised_interest_stays_interest';
