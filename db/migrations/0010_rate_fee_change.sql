-- Section 104 rate or fee change. Not a collection campaign.
-- The contractual rate, fees, instalment, and term stay on the loan.
-- Amounts are integer cents. Dates are Johannesburg recognition dates
-- (00:00 Africa/Johannesburg). Apply after 0009_layer2_staff.sql. Number 0010 keeps 0008 for collection campaigns.
-- The in-process store is lms.rate_fee_change. This file is the same shape.
-- The notice document is not stored here.

SET timezone = 'UTC';

INSERT INTO lms.ref_audit_event_type (code, category) VALUES
  ('RATE_FEE_CHANGE', 'operational')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE lms.rate_fee_change (
  organisation_id text NOT NULL,
  change_id uuid NOT NULL,
  notice_date date NOT NULL,
  effective_date date NOT NULL,
  end_date date,
  periodic_rate numeric(12, 8) CHECK (periodic_rate >= 0),
  fee_payment_frequency text CHECK (fee_payment_frequency IN (
    'weekly', 'fortnightly', 'monthly', 'quarterly', 'bi_annual', 'annual'
  )),
  fee_payment_time date,
  notice_business_days integer NOT NULL CHECK (notice_business_days = 5),
  created_by text NOT NULL CHECK (btrim(created_by) <> ''),
  created_at timestamptz NOT NULL,
  ended_by text,
  ended_at timestamptz,
  PRIMARY KEY (organisation_id, change_id),
  CHECK (end_date IS NULL OR end_date >= effective_date)
);

COMMENT ON TABLE lms.rate_fee_change IS
  'Non-campaign overlay. Null end_date has no resume date yet. notice_business_days records NCA s 104(2) and is not an election. The notice document is not stored here. A fee-only change keeps periodic_rate null and stores the new cents in rate_fee_change_fee.';

COMMENT ON COLUMN lms.rate_fee_change.periodic_rate IS
  'Requested net periodic rate. It is not written onto the loan. The concession is interest_concession on the account row. Null means no rate concession.';

COMMENT ON COLUMN lms.rate_fee_change.fee_payment_time IS
  'Johannesburg calendar date for s 104(2)(c). A clock time is not stored. Null means the fee due date is unchanged.';

CREATE TABLE lms.rate_fee_change_fee (
  organisation_id text NOT NULL,
  change_id uuid NOT NULL,
  fee_type text NOT NULL CHECK (fee_type IN (
    'initiation',
    'service',
    'credit_insurance',
    'default_administration',
    'collection_costs',
    'additional_monthly'
  )),
  cents bigint NOT NULL CHECK (cents >= 0),
  PRIMARY KEY (organisation_id, change_id, fee_type),
  FOREIGN KEY (organisation_id, change_id)
    REFERENCES lms.rate_fee_change (organisation_id, change_id)
);

COMMENT ON TABLE lms.rate_fee_change_fee IS
  'Requested net fee in integer cents. The contractual fee is not updated. The concession is stored per account.';

CREATE TABLE lms.rate_fee_change_account (
  organisation_id text NOT NULL,
  change_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  contractual_periodic_rate numeric(12, 8) NOT NULL CHECK (contractual_periodic_rate >= 0),
  contractual_base_rate numeric(12, 8) NOT NULL CHECK (contractual_base_rate >= 0),
  contractual_discount_rate numeric(12, 8) NOT NULL CHECK (contractual_discount_rate >= 0),
  contractual_end date NOT NULL,
  payment_frequency text NOT NULL,
  interest_concession numeric(12, 8) CHECK (interest_concession IS NULL OR interest_concession >= 0),
  applied_by text NOT NULL CHECK (btrim(applied_by) <> ''),
  applied_at timestamptz NOT NULL,
  PRIMARY KEY (organisation_id, change_id, loan_id),
  FOREIGN KEY (organisation_id, change_id)
    REFERENCES lms.rate_fee_change (organisation_id, change_id),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id)
);

COMMENT ON TABLE lms.rate_fee_change_account IS
  'Original contractual rate, term, and payment frequency copied at apply. Applying the change does not update loan_account or schedule_line.';

CREATE TABLE lms.rate_fee_change_fee_original (
  organisation_id text NOT NULL,
  change_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  fee_type text NOT NULL CHECK (fee_type IN (
    'initiation',
    'service',
    'credit_insurance',
    'default_administration',
    'collection_costs',
    'additional_monthly'
  )),
  contractual_cents bigint NOT NULL CHECK (contractual_cents >= 0),
  concession_cents bigint CHECK (concession_cents IS NULL OR concession_cents >= 0),
  PRIMARY KEY (organisation_id, change_id, loan_id, fee_type),
  FOREIGN KEY (organisation_id, change_id, loan_id)
    REFERENCES lms.rate_fee_change_account (organisation_id, change_id, loan_id)
);

COMMENT ON TABLE lms.rate_fee_change_fee_original IS
  'Contractual fee in integer cents, stored for disclosure. The new amount is in rate_fee_change_fee.';

CREATE TABLE lms.rate_fee_change_instalment (
  organisation_id text NOT NULL,
  change_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  sequence integer NOT NULL CHECK (sequence > 0),
  due_on date NOT NULL,
  principal_cents bigint NOT NULL CHECK (principal_cents > 0),
  PRIMARY KEY (organisation_id, change_id, loan_id, sequence),
  FOREIGN KEY (organisation_id, change_id, loan_id)
    REFERENCES lms.rate_fee_change_account (organisation_id, change_id, loan_id)
);

COMMENT ON TABLE lms.rate_fee_change_instalment IS
  'Copy of the contractual principal instalment. principal_cents is not a new instalment and schedule_line is not updated.';

CREATE INDEX rate_fee_change_account_loan
  ON lms.rate_fee_change_account (organisation_id, loan_id);
