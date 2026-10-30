-- Loan accounts, the append-only ledger, schedule versions, and statements.
--
-- organisation_id and person_id are opaque Enigma identifiers stored as text.
-- The configuration tables use uuid. That type difference is unresolved.
-- Apply after 0001_lms_owned.sql. This file does not call Enigma.

SET timezone = 'UTC';

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS lms;

DO $$ BEGIN
  CREATE ROLE lms_app NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE ROLE lms_reader NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

GRANT USAGE ON SCHEMA lms TO lms_app, lms_reader;

-- -----------------------------------------------------------------------
-- The loan and its lay-by child. One child per parent.
-- -----------------------------------------------------------------------

CREATE TABLE lms.loan_account (
  organisation_id text NOT NULL,
  loan_id uuid NOT NULL,
  person_id text NOT NULL,
  parent_loan_id uuid,
  instrument_kind text NOT NULL CHECK (instrument_kind IN ('loan', 'laybye_hold')),
  frozen_full_name text NOT NULL CHECK (btrim(frozen_full_name) <> ''),
  frozen_id_number text NOT NULL CHECK (btrim(frozen_id_number) <> ''),
  frozen_service_address text NOT NULL CHECK (btrim(frozen_service_address) <> ''),
  classification text NOT NULL,
  payment_frequency text NOT NULL CHECK (payment_frequency IN (
    'weekly', 'fortnightly', 'monthly', 'quarterly', 'bi_annual', 'annual'
  )),
  disbursement_value_date date NOT NULL,
  quoted_disbursement date,
  contractual_end date NOT NULL,
  cash_advanced_cents bigint NOT NULL CHECK (cash_advanced_cents > 0),
  capitalised_initiation_cents bigint NOT NULL DEFAULT 0 CHECK (capitalised_initiation_cents >= 0),
  initiation_capitalised boolean NOT NULL DEFAULT false,
  discount_fallen_away boolean NOT NULL DEFAULT false,
  PRIMARY KEY (organisation_id, loan_id),
  FOREIGN KEY (organisation_id, parent_loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id),
  CHECK (
    (instrument_kind = 'loan' AND parent_loan_id IS NULL)
    OR (instrument_kind = 'laybye_hold' AND parent_loan_id IS NOT NULL)
  ),
  CHECK (contractual_end >= disbursement_value_date),
  CHECK (capitalised_initiation_cents = 0 OR initiation_capitalised)
);

CREATE UNIQUE INDEX loan_one_laybye_child
  ON lms.loan_account (organisation_id, parent_loan_id)
  WHERE instrument_kind = 'laybye_hold';

COMMENT ON TABLE lms.loan_account IS
  'One row per loan or lay-by hold. The hold is a child of one parent. Identity columns are frozen at booking (LOCKED_DECISIONS §4 and §16).';

-- Elections copied at booking. Null is not a value here: an unset election
-- never becomes a row. Day count may be null only for a zero-price product.
CREATE TABLE lms.election_snapshot (
  organisation_id text NOT NULL,
  loan_id uuid NOT NULL,
  leniency_days integer NOT NULL CHECK (leniency_days >= 0),
  full_payment_threshold_percent numeric(6, 3) NOT NULL
    CHECK (full_payment_threshold_percent > 0 AND full_payment_threshold_percent <= 100),
  interest_on_deferred_initiation text NOT NULL
    CHECK (interest_on_deferred_initiation IN ('none', 'permitted')),
  repo_rate_fall text NOT NULL
    CHECK (repo_rate_fall IN ('contract_rate', 'lower_of_contract_and_cap')),
  day_count_code text CHECK (day_count_code IN ('actual_actual', 'thirty_360')),
  base_rate numeric(12, 8) NOT NULL CHECK (base_rate >= 0),
  discount_rate numeric(12, 8) NOT NULL CHECK (discount_rate >= 0 AND discount_rate <= base_rate),
  vat_on_rand_maxima text NOT NULL CHECK (vat_on_rand_maxima IN ('exclusive', 'inclusive')),
  late_disbursement text NOT NULL
    CHECK (late_disbursement IN ('adjust_instalment', 'keep_instalment')),
  partial_prepayment text NOT NULL
    CHECK (partial_prepayment IN ('shorten_term', 'drop_instalment')),
  PRIMARY KEY (organisation_id, loan_id),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id)
);

CREATE TABLE lms.schedule_version (
  organisation_id text NOT NULL,
  loan_id uuid NOT NULL,
  version_no integer NOT NULL CHECK (version_no > 0),
  effective_value_date date NOT NULL,
  reason text NOT NULL,
  late_disbursement text
    CHECK (late_disbursement IS NULL OR late_disbursement IN ('adjust_instalment', 'keep_instalment')),
  PRIMARY KEY (organisation_id, loan_id, version_no),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id)
);

CREATE TABLE lms.schedule_line (
  organisation_id text NOT NULL,
  loan_id uuid NOT NULL,
  version_no integer NOT NULL,
  sequence integer NOT NULL CHECK (sequence > 0),
  due_on date NOT NULL,
  principal_cents bigint NOT NULL CHECK (principal_cents > 0),
  PRIMARY KEY (organisation_id, loan_id, version_no, sequence),
  FOREIGN KEY (organisation_id, loan_id, version_no)
    REFERENCES lms.schedule_version (organisation_id, loan_id, version_no)
);

-- -----------------------------------------------------------------------
-- Append-only double entry. A correction is a reversal plus a new entry.
-- -----------------------------------------------------------------------

CREATE TABLE lms.ledger_sequence (
  organisation_id text PRIMARY KEY,
  last_sequence bigint NOT NULL
);

CREATE TABLE lms.ledger_transaction (
  organisation_id text NOT NULL,
  transaction_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  kind text NOT NULL,
  value_date date NOT NULL,
  recognised_at timestamptz NOT NULL,
  recognition_sequence bigint NOT NULL DEFAULT 0,
  reverses_transaction_id uuid,
  memo_rands numeric(24, 10),
  amount_cents bigint,
  attributed_due_on date,
  PRIMARY KEY (organisation_id, transaction_id),
  UNIQUE (organisation_id, recognition_sequence),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id),
  FOREIGN KEY (organisation_id, reverses_transaction_id)
    REFERENCES lms.ledger_transaction (organisation_id, transaction_id)
);

CREATE TABLE lms.ledger_entry (
  organisation_id text NOT NULL,
  entry_id uuid NOT NULL DEFAULT gen_random_uuid(),
  transaction_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  account_code text NOT NULL,
  bucket text,
  debit_cents bigint NOT NULL CHECK (debit_cents >= 0),
  credit_cents bigint NOT NULL CHECK (credit_cents >= 0),
  PRIMARY KEY (organisation_id, entry_id),
  FOREIGN KEY (organisation_id, transaction_id)
    REFERENCES lms.ledger_transaction (organisation_id, transaction_id),
  CHECK (debit_cents = 0 OR credit_cents = 0),
  CHECK (
    bucket IS NULL OR bucket IN (
      'principal',
      'interest',
      'initiation',
      'service',
      'credit_insurance',
      'default_administration',
      'collection_costs',
      'additional_monthly',
      'laybye_hold'
    )
  )
);

COMMENT ON TABLE lms.ledger_entry IS
  'Bucket balances are the sum of these rows. laybye_hold is credit-normal. The other buckets are debit-normal. LOCKED_DECISIONS §1 and §8.';

CREATE TABLE lms.default_episode (
  organisation_id text NOT NULL,
  loan_id uuid NOT NULL,
  episode_no integer NOT NULL CHECK (episode_no > 0),
  started_on date NOT NULL,
  ceiling_cents bigint NOT NULL CHECK (ceiling_cents >= 0),
  accrued_cents bigint NOT NULL DEFAULT 0 CHECK (accrued_cents >= 0),
  closed_on date,
  PRIMARY KEY (organisation_id, loan_id, episode_no),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id),
  CHECK (closed_on IS NULL OR closed_on >= started_on)
);

COMMENT ON TABLE lms.default_episode IS
  'Ceiling is unpaid principal at the first default of the episode, including pre-default capitalised initiation. The clip is not posted. LOCKED_DECISIONS §7.';

CREATE TABLE lms.service_fee_levy (
  organisation_id text NOT NULL,
  loan_id uuid NOT NULL,
  period_year integer NOT NULL,
  period_month integer NOT NULL CHECK (period_month BETWEEN 1 AND 12),
  transaction_id uuid NOT NULL,
  PRIMARY KEY (organisation_id, loan_id, period_year, period_month),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id),
  FOREIGN KEY (organisation_id, transaction_id)
    REFERENCES lms.ledger_transaction (organisation_id, transaction_id)
);

COMMENT ON TABLE lms.service_fee_levy IS
  'One service fee for the parent loan in a calendar month. The lay-by child has no row. LOCKED_DECISIONS §4.';

CREATE TABLE lms.client_statement (
  organisation_id text NOT NULL,
  statement_id uuid NOT NULL,
  person_id text NOT NULL,
  period_start date NOT NULL,
  period_end date NOT NULL,
  PRIMARY KEY (organisation_id, statement_id),
  UNIQUE (organisation_id, person_id, period_start, period_end),
  CHECK (period_end >= period_start)
);

CREATE TABLE lms.client_statement_balance (
  organisation_id text NOT NULL,
  statement_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  bucket text NOT NULL,
  opening_cents bigint NOT NULL,
  closing_cents bigint NOT NULL,
  PRIMARY KEY (organisation_id, statement_id, loan_id, bucket),
  FOREIGN KEY (organisation_id, statement_id)
    REFERENCES lms.client_statement (organisation_id, statement_id),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id)
);

COMMENT ON TABLE lms.client_statement IS
  'One statement per person per credit-provider organisation for a period. Each loan keeps its own opening and closing amounts. LOCKED_DECISIONS §12. The period bounds are not locked.';

-- -----------------------------------------------------------------------
-- Recognition sequence, reversal value date, balance, append-only.
-- -----------------------------------------------------------------------

CREATE FUNCTION lms.assign_recognition_sequence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  seq bigint;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('ledger:' || NEW.organisation_id, 0));
  INSERT INTO lms.ledger_sequence AS head (organisation_id, last_sequence)
  VALUES (NEW.organisation_id, 1)
  ON CONFLICT (organisation_id) DO UPDATE
    SET last_sequence = head.last_sequence + 1
  RETURNING last_sequence INTO seq;
  NEW.recognition_sequence := seq;
  RETURN NEW;
END;
$$;

CREATE TRIGGER ledger_recognition_sequence
  BEFORE INSERT ON lms.ledger_transaction
  FOR EACH ROW EXECUTE FUNCTION lms.assign_recognition_sequence();

CREATE FUNCTION lms.enforce_reversal_value_date() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  original_date date;
BEGIN
  IF NEW.reverses_transaction_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT value_date INTO original_date
  FROM lms.ledger_transaction
  WHERE organisation_id = NEW.organisation_id
    AND transaction_id = NEW.reverses_transaction_id;
  IF original_date IS NULL THEN
    RAISE EXCEPTION 'reversal target is not in this organisation';
  END IF;
  IF NEW.value_date <> original_date THEN
    RAISE EXCEPTION 'reversal value_date must be the original recognised value date';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER ledger_reversal_value_date
  BEFORE INSERT ON lms.ledger_transaction
  FOR EACH ROW EXECUTE FUNCTION lms.enforce_reversal_value_date();

CREATE FUNCTION lms.reject_ledger_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ledger is append-only; a correction is a reversal and a new entry';
END;
$$;

CREATE TRIGGER ledger_transaction_append_only
  BEFORE UPDATE OR DELETE ON lms.ledger_transaction
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE TRIGGER ledger_entry_append_only
  BEFORE UPDATE OR DELETE ON lms.ledger_entry
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE TRIGGER election_snapshot_append_only
  BEFORE UPDATE OR DELETE ON lms.election_snapshot
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE TRIGGER schedule_version_append_only
  BEFORE UPDATE OR DELETE ON lms.schedule_version
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE TRIGGER schedule_line_append_only
  BEFORE UPDATE OR DELETE ON lms.schedule_line
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE TRIGGER service_fee_append_only
  BEFORE UPDATE OR DELETE ON lms.service_fee_levy
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE TRIGGER statement_append_only
  BEFORE UPDATE OR DELETE ON lms.client_statement
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE TRIGGER statement_balance_append_only
  BEFORE UPDATE OR DELETE ON lms.client_statement_balance
  FOR EACH ROW EXECUTE FUNCTION lms.reject_ledger_mutation();

CREATE FUNCTION lms.reject_frozen_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.frozen_full_name IS DISTINCT FROM OLD.frozen_full_name
     OR NEW.frozen_id_number IS DISTINCT FROM OLD.frozen_id_number
     OR NEW.frozen_service_address IS DISTINCT FROM OLD.frozen_service_address
     OR NEW.organisation_id IS DISTINCT FROM OLD.organisation_id
     OR NEW.person_id IS DISTINCT FROM OLD.person_id
     OR NEW.loan_id IS DISTINCT FROM OLD.loan_id
     OR NEW.parent_loan_id IS DISTINCT FROM OLD.parent_loan_id
     OR NEW.instrument_kind IS DISTINCT FROM OLD.instrument_kind
     OR NEW.classification IS DISTINCT FROM OLD.classification
     OR NEW.payment_frequency IS DISTINCT FROM OLD.payment_frequency
     OR NEW.disbursement_value_date IS DISTINCT FROM OLD.disbursement_value_date
     OR NEW.quoted_disbursement IS DISTINCT FROM OLD.quoted_disbursement
     OR NEW.contractual_end IS DISTINCT FROM OLD.contractual_end
     OR NEW.cash_advanced_cents IS DISTINCT FROM OLD.cash_advanced_cents
     OR NEW.capitalised_initiation_cents IS DISTINCT FROM OLD.capitalised_initiation_cents
     OR NEW.initiation_capitalised IS DISTINCT FROM OLD.initiation_capitalised
  THEN
    RAISE EXCEPTION 'facts frozen at booking cannot be rewritten';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER loan_identity_frozen
  BEFORE UPDATE ON lms.loan_account
  FOR EACH ROW EXECUTE FUNCTION lms.reject_frozen_identity();

CREATE FUNCTION lms.protect_episode() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'an in-duplum episode is not deleted';
  END IF;
  IF NEW.organisation_id IS DISTINCT FROM OLD.organisation_id
     OR NEW.loan_id IS DISTINCT FROM OLD.loan_id
     OR NEW.episode_no IS DISTINCT FROM OLD.episode_no
     OR NEW.started_on IS DISTINCT FROM OLD.started_on
     OR NEW.ceiling_cents IS DISTINCT FROM OLD.ceiling_cents
  THEN
    RAISE EXCEPTION 'the in-duplum ceiling stays fixed for the episode';
  END IF;
  IF OLD.closed_on IS NOT NULL AND NEW.closed_on IS DISTINCT FROM OLD.closed_on THEN
    RAISE EXCEPTION 'a closed in-duplum episode stays closed';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER episode_ceiling_fixed
  BEFORE UPDATE OR DELETE ON lms.default_episode
  FOR EACH ROW EXECUTE FUNCTION lms.protect_episode();

CREATE FUNCTION lms.assert_transaction_balanced() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  debit bigint;
  credit bigint;
BEGIN
  SELECT COALESCE(SUM(debit_cents), 0), COALESCE(SUM(credit_cents), 0)
    INTO debit, credit
  FROM lms.ledger_entry
  WHERE organisation_id = NEW.organisation_id
    AND transaction_id = NEW.transaction_id;
  IF debit <> credit THEN
    RAISE EXCEPTION 'transaction % is not balanced', NEW.transaction_id;
  END IF;
  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_entries_balance
  AFTER INSERT ON lms.ledger_entry
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION lms.assert_transaction_balanced();

CREATE FUNCTION lms.loan_bucket_balance(
  p_organisation_id text,
  p_loan_id uuid,
  p_bucket text,
  p_as_of date
) RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(SUM(
    CASE
      WHEN p_bucket = 'laybye_hold' THEN entry.credit_cents - entry.debit_cents
      ELSE entry.debit_cents - entry.credit_cents
    END
  ), 0)
  FROM lms.ledger_entry AS entry
  JOIN lms.ledger_transaction AS tx
    ON tx.organisation_id = entry.organisation_id
   AND tx.transaction_id = entry.transaction_id
  WHERE entry.organisation_id = p_organisation_id
    AND entry.loan_id = p_loan_id
    AND entry.bucket = p_bucket
    AND tx.value_date <= p_as_of;
$$;

COMMENT ON FUNCTION lms.loan_bucket_balance(text, uuid, text, date) IS
  'Debit-normal bucket, except laybye_hold which is credit-normal. Value date, not recognition time. LOCKED_DECISIONS §1 and §4.';

-- -----------------------------------------------------------------------
-- Tenant isolation. Text identifiers, so this policy does not cast to uuid.
-- -----------------------------------------------------------------------

DO $$
DECLARE
  tenant text;
BEGIN
  FOREACH tenant IN ARRAY ARRAY[
    'loan_account',
    'election_snapshot',
    'schedule_version',
    'schedule_line',
    'ledger_sequence',
    'ledger_transaction',
    'ledger_entry',
    'default_episode',
    'service_fee_levy',
    'client_statement',
    'client_statement_balance'
  ]
  LOOP
    EXECUTE format('ALTER TABLE lms.%I ENABLE ROW LEVEL SECURITY', tenant);
    EXECUTE format('ALTER TABLE lms.%I FORCE ROW LEVEL SECURITY', tenant);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON lms.%I USING (organisation_id = current_setting(''lms.organisation_id'', true)) WITH CHECK (organisation_id = current_setting(''lms.organisation_id'', true))',
      tenant
    );
    EXECUTE format(
      'GRANT SELECT ON lms.%I TO lms_app, lms_reader',
      tenant
    );
    EXECUTE format('GRANT INSERT ON lms.%I TO lms_app', tenant);
  END LOOP;
END $$;

GRANT UPDATE (discount_fallen_away) ON lms.loan_account TO lms_app;
GRANT UPDATE (accrued_cents, closed_on) ON lms.default_episode TO lms_app;
GRANT UPDATE (last_sequence) ON lms.ledger_sequence TO lms_app;
