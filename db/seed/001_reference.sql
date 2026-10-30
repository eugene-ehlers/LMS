-- Reference data transcribed from the instruments cited on each row.
-- Apply after db/migrations/0001_lms_owned.sql, as the migration role.
-- Holiday dates for 2026-2032 are appended by scripts/render_holidays.py
-- into this file under the marker below. Do not hand-edit that block.

SET timezone = 'UTC';

INSERT INTO lms.ref_instrument (code, citation, effective_from) VALUES
  ('NCA_34_2005', 'National Credit Act 34 of 2005, Government Gazette 28619, 15 March 2006', '2006-03-15'),
  ('GN_R489_2006', 'National Credit Regulations, Government Notice R489, 31 May 2006', '2006-06-01'),
  ('GN_713_2006', 'Determination of thresholds, Government Notice 713, Government Gazette 28893, 1 June 2006', '2006-06-01'),
  ('GN_1080_2015', 'Review of limitations on fees and interest rates, Government Notice 1080, Government Gazette 39379, 6 November 2015, effective 6 May 2016', '2016-05-06'),
  ('CPA_68_2008', 'Consumer Protection Act 68 of 2008, section 62', '2011-04-01'),
  ('CPA_R293_2011', 'Consumer Protection Act regulations, Government Notice R293, Government Gazette 34180, regulation 34', '2011-04-01'),
  ('PUBLIC_HOLIDAYS_ACT_1994', 'Public Holidays Act 36 of 1994, including section 2(1) Sunday observance', '1994-01-01'),
  ('SARB_MPC_2026_09_23', 'South African Reserve Bank Monetary Policy Committee statement, 23 September 2026: repurchase rate 7.25 percent, effective 25 September 2026', '2026-09-25');

INSERT INTO lms.ref_credit_classification (code, statute_item, rate_period, description) VALUES
  ('mortgage', 'Table A item 1', 'year', 'Mortgage agreements'),
  ('credit_facility', 'Table A item 2', 'year', 'Credit facilities'),
  ('unsecured', 'Table A item 3', 'year', 'Unsecured credit transactions'),
  ('developmental_small_business', 'Table A item 4.1', 'year', 'Developmental credit for a small business'),
  ('developmental_low_income_housing', 'Table A item 4.2', 'year', 'Developmental credit for low income housing'),
  ('short_term', 'Table A item 5', 'month', 'Short-term credit transactions, regulation 39'),
  ('other', 'Table A item 6', 'year', 'Other credit agreements'),
  ('incidental', 'Table A item 7', 'month', 'Incidental credit agreements'),
  ('zero_cost', NULL, 'none', 'Day-1 zero-cost BNPL. Not priced under Table A. A charge requires a new classification, not a silent fee.'),
  ('cpa_layby', NULL, 'none', 'CPA section 62 lay-by of goods. Not an NCA credit agreement while no credit charge is levied.');

INSERT INTO lms.ref_day_count_convention (code, period, divisor_kind, statute_ref) VALUES
  ('short_term_actual_days', 'month', 'actual_month', 'Regulation 40(2)(b) and 40(2)(c)(iv), actual days in the month'),
  ('short_term_30_day', 'month', 'fixed_30', 'Regulation 40(2)(c)(iv), 30-day month. Not within 0.1% of actual days over a year.'),
  ('annual_365', 'year', 'fixed_365', 'Regulation 40(2)(a) and 40(2)(c)(iii), divisor 365'),
  ('annual_actual', 'year', 'actual_year', 'Regulation 40(2)(c)(iii), 365 or 366. The agreement must pin one.');

INSERT INTO lms.ref_balance_code (code, s126_tier, in_duplum) VALUES
  ('interest', 1, true),
  ('initiation_fee', 2, true),
  ('service_fee', 2, true),
  ('default_admin', 2, true),
  ('collection', 2, true),
  ('credit_insurance', 2, true),
  ('principal', 3, false),
  ('early_termination', 2, false),
  ('deposit', NULL, false),
  ('layby_penalty', NULL, false);

INSERT INTO lms.ref_allocation_tier (tier, statute_text) VALUES
  (1, 'Section 126(3)(a): firstly, to satisfy any due or unpaid interest charges'),
  (2, 'Section 126(3)(b): secondly, to satisfy any due or unpaid fees or charges'),
  (3, 'Section 126(3)(c): thirdly, to reduce the amount of the principal debt');

INSERT INTO lms.ref_status_code (code, opens_in_duplum, terminal, description) VALUES
  ('quote', false, false, 'Quoted, not yet an agreement'),
  ('pending_disbursement', false, false, 'Agreement concluded, advance not yet paid'),
  ('active', false, false, 'Advance paid and no operator default flag. Payment arrears still open in duplum.'),
  ('arrears', false, false, 'Amount is overdue. The arrears position, not this label, is what the engine reads.'),
  ('default_marked', true, false, 'Operator has recorded a default, including a non-payment breach'),
  ('debt_review', false, false, 'Section 86 flag. Does not itself start or stop in duplum.'),
  ('enforcement', true, false, 'Enforcement step recorded'),
  ('handed_over', true, false, 'Handed to a collector or attorney'),
  ('settled', false, true, 'Section 125 settlement, or contractual settlement at maturity'),
  ('early_settled', false, true, 'Settled before the contractual end date'),
  ('written_off', false, true, 'Balance written off'),
  ('cancelled', false, true, 'Cancelled before disbursement'),
  ('rescinded', false, true, 'Rescinded before disbursement');

INSERT INTO lms.ref_status_transition (from_code, to_code) VALUES
  ('quote', 'pending_disbursement'),
  ('quote', 'cancelled'),
  ('pending_disbursement', 'active'),
  ('pending_disbursement', 'cancelled'),
  ('pending_disbursement', 'rescinded'),
  ('active', 'arrears'),
  ('active', 'settled'),
  ('active', 'early_settled'),
  ('active', 'debt_review'),
  ('active', 'default_marked'),
  ('active', 'written_off'),
  ('arrears', 'active'),
  ('arrears', 'default_marked'),
  ('arrears', 'debt_review'),
  ('arrears', 'settled'),
  ('arrears', 'early_settled'),
  ('arrears', 'written_off'),
  ('arrears', 'enforcement'),
  ('default_marked', 'enforcement'),
  ('default_marked', 'arrears'),
  ('default_marked', 'debt_review'),
  ('default_marked', 'settled'),
  ('default_marked', 'written_off'),
  ('default_marked', 'handed_over'),
  ('debt_review', 'active'),
  ('debt_review', 'arrears'),
  ('debt_review', 'settled'),
  ('debt_review', 'written_off'),
  ('enforcement', 'handed_over'),
  ('enforcement', 'settled'),
  ('enforcement', 'written_off'),
  ('handed_over', 'settled'),
  ('handed_over', 'written_off');

INSERT INTO lms.ref_feature_flag (code, description) VALUES
  ('origination_enabled', 'Allow new agreements for this organisation. Does not change a price.'),
  ('debit_orders_enabled', 'Submit debit orders. Does not change allocation.'),
  ('statements_enabled', 'Generate statements.'),
  ('bnpl_enabled', 'Offer the zero-cost BNPL product, still subject to Enigma enrolment.'),
  ('layby_security_enabled', 'Offer the short-term loan plus zero-interest deposit.');

INSERT INTO lms.ref_audit_event_type (code, category) VALUES
  ('INTEREST_ACCRUED', 'financial'),
  ('INTEREST_SUPPRESSED', 'financial'),
  ('FEE_ACCRUED', 'financial'),
  ('FEE_SUPPRESSED', 'financial'),
  ('PAYMENT_RECEIVED', 'financial'),
  ('PAYMENT_ALLOCATED', 'financial'),
  ('PRINCIPAL_ADVANCED', 'financial'),
  ('SETTLEMENT_APPLIED', 'financial'),
  ('BALANCE_WRITTEN_OFF', 'financial'),
  ('POSTING_REVERSED', 'financial'),
  ('DEPOSIT_RECEIVED', 'financial'),
  ('DEPOSIT_RELEASED', 'financial'),
  ('SETOFF_APPLIED', 'financial'),
  ('TERMS_PUBLISHED', 'operational'),
  ('ORGANISATION_SETTINGS_CHANGED', 'operational'),
  ('BRAND_CHANGED', 'operational'),
  ('FEATURE_FLAG_CHANGED', 'operational'),
  ('AGREEMENT_STATUS_CHANGED', 'operational'),
  ('STATEMENT_ISSUED', 'operational'),
  ('DEBIT_ORDER_SUBMITTED', 'operational'),
  ('LOAN_NUMBER_ISSUED', 'operational'),
  ('RECEIPT_HELD_UNAPPLIED', 'operational'),
  ('CREDIT_LIFE_PREMIUM_RECEIVED', 'operational'),
  ('RETURNED_UNPAID_FLAGGED', 'operational'),
  ('RECOVERY_NOT_POSTED', 'operational'),
  ('REFERENCE_DATA_PUBLISHED', 'operational'),
  ('SETTLEMENT_QUOTED', 'operational'),
  ('SETTLEMENT_REJECTED', 'operational'),
  ('SETTLEMENT_READVANCE', 'operational');

INSERT INTO lms.ref_audit_event_type (code, category) VALUES
  ('COLLECTION_CAMPAIGN_CHANGED', 'operational')
ON CONFLICT (code) DO NOTHING;

-- Table A as substituted by GN 1080, effective 6 May 2016.
-- Margins are fractions: 0.21 means 21 percentage points over RR.
INSERT INTO lms.ref_interest_cap (
  classification_code, effective_from, cap_kind, repo_margin, periodic_rate, subsequent_periodic_rate, instrument_code
) VALUES
  ('mortgage', '2016-05-06', 'repo_plus', 0.12000000, NULL, NULL, 'GN_1080_2015'),
  ('credit_facility', '2016-05-06', 'repo_plus', 0.14000000, NULL, NULL, 'GN_1080_2015'),
  ('unsecured', '2016-05-06', 'repo_plus', 0.21000000, NULL, NULL, 'GN_1080_2015'),
  ('developmental_small_business', '2016-05-06', 'repo_plus', 0.27000000, NULL, NULL, 'GN_1080_2015'),
  ('developmental_low_income_housing', '2016-05-06', 'repo_plus', 0.27000000, NULL, NULL, 'GN_1080_2015'),
  ('other', '2016-05-06', 'repo_plus', 0.17000000, NULL, NULL, 'GN_1080_2015'),
  ('short_term', '2016-05-06', 'fixed_periodic', NULL, 0.05000000, 0.03000000, 'GN_1080_2015'),
  ('incidental', '2016-05-06', 'fixed_periodic', NULL, 0.02000000, NULL, 'GN_1080_2015');

-- Table B. Incidental initiation is nil. "The amount of the agreement is
-- the amount deferred" remains the 2006 note under Table B; GN 1080's
-- fetched text substituted the table and did not restate the note.
INSERT INTO lms.ref_initiation_fee_cap (
  classification_code, effective_from, flat_cents, threshold_cents, marginal_rate, absolute_cents, instrument_code
) VALUES
  ('mortgage', '2016-05-06', 110000, 1000000, 0.10000000, 525000, 'GN_1080_2015'),
  ('credit_facility', '2016-05-06', 16500, 100000, 0.10000000, 105000, 'GN_1080_2015'),
  ('unsecured', '2016-05-06', 16500, 100000, 0.10000000, 105000, 'GN_1080_2015'),
  ('short_term', '2016-05-06', 16500, 100000, 0.10000000, 105000, 'GN_1080_2015'),
  ('other', '2016-05-06', 16500, 100000, 0.10000000, 105000, 'GN_1080_2015'),
  ('developmental_small_business', '2016-05-06', 27500, 100000, 0.10000000, 260000, 'GN_1080_2015'),
  ('developmental_low_income_housing', '2016-05-06', 55000, 100000, 0.10000000, 260000, 'GN_1080_2015'),
  ('incidental', '2016-05-06', 0, 0, 0.00000000, 0, 'GN_1080_2015');

INSERT INTO lms.ref_service_fee_cap (effective_from, monthly_cents, instrument_code) VALUES
  ('2016-05-06', 6000, 'GN_1080_2015');

INSERT INTO lms.ref_threshold (code, effective_from, amount_cents, month_count, instrument_code) VALUES
  ('agreement_size_lower', '2006-06-01', 1500000, NULL, 'GN_713_2006'),
  ('agreement_size_higher', '2006-06-01', 25000000, NULL, 'GN_713_2006'),
  ('short_term_deferred', '2006-06-01', 800000, NULL, 'GN_R489_2006'),
  ('short_term_max_months', '2006-06-01', NULL, 6, 'GN_R489_2006');

INSERT INTO lms.ref_charge_rule (code, effective_from, rule_kind, ratio, notes, instrument_code) VALUES
  ('initiation_principal_ratio', '2006-06-01', 'principal_ratio', 0.15000000,
   'Regulation 43(3): an initiation fee may never exceed 15% of the principal debt. Applied as well as Table B. Day-1 uses the cash advanced as the base; see the interpretation set.',
   'GN_R489_2006'),
  ('layby_cancellation_penalty', '2011-04-01', 'percent_of_price', 0.01000000,
   'CPA regulation 34: a lay-by cancellation penalty must be reasonable and may not exceed 1% of the full purchase price. Nil if undisclosed, or if the consumer died or was hospitalised (section 62(5)). Not applicable to a cash security deposit.',
   'CPA_R293_2011'),
  ('default_admin', '2006-06-01', 'tariff_required', NULL,
   'Regulation 46: each letter necessarily written under Part C of Chapter 6, not exceeding the Magistrates'' Courts tariff for a registered letter of demand in an undefended action, plus reasonable necessary delivery expenses. No rand amount is seeded. Posting fails closed until ref_tariff_amount has a covering row.',
   'GN_R489_2006'),
  ('collection', '2006-06-01', 'tariff_required', NULL,
   'Regulation 47: collection costs may not exceed the costs incurred, and are limited by the Supreme Court Act, Magistrates'' Courts Act, Attorneys Act, or Debt Collectors Act, whichever applies. No rand amount is seeded. Posting fails closed until a tariff row is loaded.',
   'GN_R489_2006'),
  ('early_termination', '2006-06-01', 'formula_unsettled', NULL,
   'Section 125(2)(c) applies only to a large agreement. No prescribed charge was found in the 2006 regulations or GN 1080, so sub-paragraph (i) points at sub-paragraph (ii): up to the interest that would have been payable for three months less notice given. The constant-balance reading is pending counsel. Day-1 unsecured products keep principal below R250 000 so the charge is not reached.',
   'NCA_34_2005');

INSERT INTO lms.ref_reference_rate (code, effective_from, annual_rate, confidence, instrument_code) VALUES
  ('SARB_REPO', '2026-09-25', 0.07250000, 'confirmed', 'SARB_MPC_2026_09_23');

-- Earlier repurchase-rate history is not seeded. Secondary reports put the
-- previous rate at 7.00% from 29 May 2026. That row is omitted until the
-- SARB statement is filed and marked confirmed. A variable-rate accrual
-- before 25 September 2026 fails closed.

INSERT INTO lms.ref_interpretation_set (id, code, effective_from, status) VALUES
  ('00000000-0000-4000-8000-0000000000a1', 'day1-adopted', '2006-06-01', 'adopted');

INSERT INTO lms.ref_interpretation_choice (
  set_id, question_code, adopted_option, alternative_option, authority, effect, notes
) VALUES
  ('00000000-0000-4000-8000-0000000000a1', 'initiation_base', 'cash_advanced', 'grossed_principal', 'pending_counsel', 'safe_ceiling',
   'Table B uses the amount deferred, and regulation 43(3) uses the principal debt. Both are circular once the fee is deferred. Day-1 prices the fee on the cash advanced, which is less than or equal to the grossed fixed point.'),
  ('00000000-0000-4000-8000-0000000000a1', 'vat_on_prescribed_cap', 'cap_is_consumer_maximum', 'vat_added_on_top', 'pending_counsel', 'safe_ceiling',
   'GN 1080 states rand amounts and does not mention VAT. Day-1 does not add VAT on top of a gazetted figure. A VAT vendor splits 15/115 inside that figure.'),
  ('00000000-0000-4000-8000-0000000000a1', 'short_term_ordinal', 'per_organisation_and_calendar_year', 'lifetime_with_organisation', 'text', 'locked',
   'Decision 13. A subsequent short-term loan is counted per credit-provider organisation and per calendar year. A quote that does not disburse does not count.'),
  ('00000000-0000-4000-8000-0000000000a1', 'in_duplum_headroom', 'cumulative', 'floating', 'text', 'locked',
   'Locked decision 7, aligned with section 103(5) and Nedbank Ltd v National Credit Regulator [2011] ZASCA 35. The base is unpaid principal at the first default, including pre-default capitalised initiation. Payments do not reset the counter. Post-default accruals stay charges.'),
  ('00000000-0000-4000-8000-0000000000a1', 'capitalised_interest_stays_interest', 'pre_default_initiation_joins_principal', 'initiation_stays_a_fee', 'text', 'locked',
   'Locked decisions 2 and 7. A capitalised initiation fee is part of principal. If it is not capitalised it stays a due fee under section 126. Post-default interest and fees remain charges for section 103(5) and section 126 even when a statement shows them as capitalised.'),
  ('00000000-0000-4000-8000-0000000000a1', 's126_prepayment', 'reduce_principal', 'hold_for_future_instalments', 'text', 'safe_ceiling',
   'Section 126(3)(c) reduces the principal debt as of the date of receipt. A suspense credit for future instalments is not in the section.'),
  ('00000000-0000-4000-8000-0000000000a1', 'fee_suborder', 'oldest_then_pro_rata', 'provider_chosen', 'pending_counsel', 'does_not_change_total',
   'Section 126(3)(b) is one bucket. Oldest payable date first, and largest-remainder pro rata on the same day, does not change how much of the payment is applied to fees.'),
  ('00000000-0000-4000-8000-0000000000a1', 's126_interest_scope', 'already_payable', 'include_unposted_accrual', 'pending_counsel', 'safe_ceiling',
   'Ordinary payments allocate to interest the agreement has already made payable. Regulation 40 adds interest monthly, and section 103(3) forbids debiting a day''s interest before the end of that day. Section 125 settlement still includes interest up to the settlement date.'),
  ('00000000-0000-4000-8000-0000000000a1', 'inception_service_day', 'opening_period_disbursement_to_first_due', 'calendar_month_of_conclusion', 'text', 'locked',
   'Locked decision 9, citing regulation 44(4) and Micro Finance South Africa v National Credit Regulator. Pro-rata only from disbursement to the first payment due. Every later month, including the settlement month, is the full monthly fee, capped at R60.'),
  ('00000000-0000-4000-8000-0000000000a1', 'settlement_month_service_fee', 'full_month', 'pro_rata', 'text', 'locked',
   'Locked decision 9. The settlement month is a full monthly service fee, subject to the R60 cap. A product cannot prorate it.'),
  ('00000000-0000-4000-8000-0000000000a1', 'cap_test_date', 'stored_per_organisation_or_product', 'platform_default', 'text', 'locked',
   'Locked decision 11. When the repo rate falls the provider has already chosen contract_rate or lower_of_contract_and_cap. There is no platform default. A null choice fails closed. Option B also requires the section 104 notice.'),
  ('00000000-0000-4000-8000-0000000000a1', 'defer_initiation', 'only_after_upfront_declined', 'defer_without_offer', 'pending_counsel', 'safe_ceiling',
   'Section 102(1)(a) requires that offer for instalment, mortgage, secured loan, and lease. It does not name short-term or unsecured credit. Day-1 still defers the fee only after the consumer is offered the chance to pay it upfront and declines. If cash plus the fee would exceed R8 000, the agreement is not originated as short-term.'),
  ('00000000-0000-4000-8000-0000000000a1', 'default_trigger', 'due_plus_leniency_and_threshold', 'immediate_arrears', 'text', 'locked',
   'Locked decision 6. One test for in duplum and for collections. Flag only on the contractual due date plus the configured leniency days, and only if receipts are below the configured percent of the instalment. Leniency does not pause interest.'),
  ('00000000-0000-4000-8000-0000000000a1', 'early_termination_base', 'constant_outstanding_balance', 'scheduled_instalment_interest', 'pending_counsel', 'either_way',
   'Used only for a large agreement. Day-1 product templates stay below R250 000.'),
  ('00000000-0000-4000-8000-0000000000a1', 'interest_rounding', 'half_up_then_clamp', 'floor_each_day', 'tolerance', 'safe_ceiling',
   'Regulation 40(4) allows 0.1% a year. Daily amounts stay unrounded, the month (or a payment slice) is half-up to the cent, then clamped to the cap.'),
  ('00000000-0000-4000-8000-0000000000a1', 'intraday_balance', 'calendar_day_at_0000', 'end_of_day', 'text', 'locked',
   'Locked decision 1. Start of the day is 00:00 Africa/Johannesburg. A loan, settlement, or deposit at any time on a calendar day is value-dated 00:00 that day, before that day''s interest.');

-- HOLIDAYS 2026-2032
-- generated from lms_config.calendar.public_holidays; do not edit by hand
INSERT INTO lms.ref_public_holiday (holiday_date, name, source) VALUES
  ('2026-01-01', 'New Year''s Day', 'act'),
  ('2026-03-21', 'Human Rights Day', 'act'),
  ('2026-04-03', 'Good Friday', 'act'),
  ('2026-04-06', 'Family Day', 'act'),
  ('2026-04-27', 'Freedom Day', 'act'),
  ('2026-06-16', 'Youth Day', 'act'),
  ('2026-08-09', 'National Women''s Day', 'act'),
  ('2026-08-10', 'National Women''s Day (observed)', 'sunday_rule'),
  ('2026-09-24', 'Heritage Day', 'act'),
  ('2026-12-16', 'Day of Reconciliation', 'act'),
  ('2026-12-25', 'Christmas Day', 'act'),
  ('2026-12-26', 'Day of Goodwill', 'act'),
  ('2027-01-01', 'New Year''s Day', 'act'),
  ('2027-03-21', 'Human Rights Day', 'act'),
  ('2027-03-22', 'Human Rights Day (observed)', 'sunday_rule'),
  ('2027-03-26', 'Good Friday', 'act'),
  ('2027-03-29', 'Family Day', 'act'),
  ('2027-04-27', 'Freedom Day', 'act'),
  ('2027-06-16', 'Youth Day', 'act'),
  ('2027-08-09', 'National Women''s Day', 'act'),
  ('2027-09-24', 'Heritage Day', 'act'),
  ('2027-12-16', 'Day of Reconciliation', 'act'),
  ('2027-12-25', 'Christmas Day', 'act'),
  ('2027-12-26', 'Day of Goodwill', 'act'),
  ('2027-12-27', 'Day of Goodwill (observed)', 'sunday_rule'),
  ('2028-01-01', 'New Year''s Day', 'act'),
  ('2028-03-21', 'Human Rights Day', 'act'),
  ('2028-04-14', 'Good Friday', 'act'),
  ('2028-04-17', 'Family Day', 'act'),
  ('2028-04-27', 'Freedom Day', 'act'),
  ('2028-06-16', 'Youth Day', 'act'),
  ('2028-08-09', 'National Women''s Day', 'act'),
  ('2028-09-24', 'Heritage Day', 'act'),
  ('2028-09-25', 'Heritage Day (observed)', 'sunday_rule'),
  ('2028-12-16', 'Day of Reconciliation', 'act'),
  ('2028-12-25', 'Christmas Day', 'act'),
  ('2028-12-26', 'Day of Goodwill', 'act'),
  ('2029-01-01', 'New Year''s Day', 'act'),
  ('2029-03-21', 'Human Rights Day', 'act'),
  ('2029-03-30', 'Good Friday', 'act'),
  ('2029-04-02', 'Family Day', 'act'),
  ('2029-04-27', 'Freedom Day', 'act'),
  ('2029-06-16', 'Youth Day', 'act'),
  ('2029-08-09', 'National Women''s Day', 'act'),
  ('2029-09-24', 'Heritage Day', 'act'),
  ('2029-12-16', 'Day of Reconciliation', 'act'),
  ('2029-12-17', 'Day of Reconciliation (observed)', 'sunday_rule'),
  ('2029-12-25', 'Christmas Day', 'act'),
  ('2029-12-26', 'Day of Goodwill', 'act'),
  ('2030-01-01', 'New Year''s Day', 'act'),
  ('2030-03-21', 'Human Rights Day', 'act'),
  ('2030-04-19', 'Good Friday', 'act'),
  ('2030-04-22', 'Family Day', 'act'),
  ('2030-04-27', 'Freedom Day', 'act'),
  ('2030-06-16', 'Youth Day', 'act'),
  ('2030-06-17', 'Youth Day (observed)', 'sunday_rule'),
  ('2030-08-09', 'National Women''s Day', 'act'),
  ('2030-09-24', 'Heritage Day', 'act'),
  ('2030-12-16', 'Day of Reconciliation', 'act'),
  ('2030-12-25', 'Christmas Day', 'act'),
  ('2030-12-26', 'Day of Goodwill', 'act'),
  ('2031-01-01', 'New Year''s Day', 'act'),
  ('2031-03-21', 'Human Rights Day', 'act'),
  ('2031-04-11', 'Good Friday', 'act'),
  ('2031-04-14', 'Family Day', 'act'),
  ('2031-04-27', 'Freedom Day', 'act'),
  ('2031-04-28', 'Freedom Day (observed)', 'sunday_rule'),
  ('2031-06-16', 'Youth Day', 'act'),
  ('2031-08-09', 'National Women''s Day', 'act'),
  ('2031-09-24', 'Heritage Day', 'act'),
  ('2031-12-16', 'Day of Reconciliation', 'act'),
  ('2031-12-25', 'Christmas Day', 'act'),
  ('2031-12-26', 'Day of Goodwill', 'act'),
  ('2032-01-01', 'New Year''s Day', 'act'),
  ('2032-03-21', 'Human Rights Day', 'act'),
  ('2032-03-22', 'Human Rights Day (observed)', 'sunday_rule'),
  ('2032-03-26', 'Good Friday', 'act'),
  ('2032-03-29', 'Family Day', 'act'),
  ('2032-04-27', 'Freedom Day', 'act'),
  ('2032-06-16', 'Youth Day', 'act'),
  ('2032-08-09', 'National Women''s Day', 'act'),
  ('2032-09-24', 'Heritage Day', 'act'),
  ('2032-12-16', 'Day of Reconciliation', 'act'),
  ('2032-12-25', 'Christmas Day', 'act'),
  ('2032-12-26', 'Day of Goodwill', 'act'),
  ('2032-12-27', 'Day of Goodwill (observed)', 'sunday_rule');
