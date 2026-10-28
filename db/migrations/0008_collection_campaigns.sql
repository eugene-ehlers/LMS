-- Collection campaigns. A temporary rate, fee, or payment-holiday overlay.
-- The contractual rate, fees, instalment, and term stay on the loan.
-- Amounts are integer cents. Dates are Johannesburg recognition dates
-- (00:00 Africa/Johannesburg). Apply after 0004_ledger_accounts.sql.
-- The in-process store is lms.collection_campaigns. This file is the same shape.

SET timezone = 'UTC';

INSERT INTO lms.ref_audit_event_type (code, category) VALUES
  ('COLLECTION_CAMPAIGN_CHANGED', 'operational')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE lms.collection_campaign (
  organisation_id text NOT NULL,
  campaign_id uuid NOT NULL,
  start_date date NOT NULL,
  end_date date,
  rate_reduction numeric(12, 8) NOT NULL CHECK (rate_reduction >= 0),
  payment_holiday boolean NOT NULL,
  notice_date date NOT NULL,
  notice_business_days integer NOT NULL CHECK (notice_business_days = 5),
  created_by text NOT NULL CHECK (btrim(created_by) <> ''),
  created_at timestamptz NOT NULL,
  PRIMARY KEY (organisation_id, campaign_id),
  CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE lms.collection_campaign IS
  'Servicing overlay. Null end_date is open-ended. notice_business_days records NCA s 104(2) and is not an election. The notice document is not stored here.';

COMMENT ON COLUMN lms.collection_campaign.rate_reduction IS
  'Non-negative reduction in the same unit as the contractual periodic rate. Zero leaves the rate unchanged. A negative value is an increase and is rejected.';

CREATE TABLE lms.collection_campaign_fee (
  organisation_id text NOT NULL,
  campaign_id uuid NOT NULL,
  fee_type text NOT NULL CHECK (fee_type IN (
    'initiation',
    'service',
    'credit_insurance',
    'default_administration',
    'collection_costs',
    'additional_monthly'
  )),
  reduction_cents bigint NOT NULL CHECK (reduction_cents >= 0),
  PRIMARY KEY (organisation_id, campaign_id, fee_type),
  FOREIGN KEY (organisation_id, campaign_id)
    REFERENCES lms.collection_campaign (organisation_id, campaign_id)
);

COMMENT ON TABLE lms.collection_campaign_fee IS
  'Fee reduction in integer cents. Zero is an explicit unchanged fee. The contractual fee is not updated.';

CREATE TABLE lms.collection_campaign_application (
  organisation_id text NOT NULL,
  campaign_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  contractual_base_rate numeric(12, 8) NOT NULL CHECK (contractual_base_rate >= 0),
  contractual_discount_rate numeric(12, 8) NOT NULL CHECK (contractual_discount_rate >= 0),
  contractual_periodic_rate numeric(12, 8) NOT NULL CHECK (contractual_periodic_rate >= 0),
  contractual_end date NOT NULL,
  applied_by text NOT NULL CHECK (btrim(applied_by) <> ''),
  applied_at timestamptz NOT NULL,
  PRIMARY KEY (organisation_id, campaign_id, loan_id),
  FOREIGN KEY (organisation_id, campaign_id)
    REFERENCES lms.collection_campaign (organisation_id, campaign_id),
  FOREIGN KEY (organisation_id, loan_id)
    REFERENCES lms.loan_account (organisation_id, loan_id)
);

COMMENT ON TABLE lms.collection_campaign_application IS
  'Original contractual rate and term copied at apply. Applying the campaign does not update loan_account or schedule_line.';

CREATE TABLE lms.collection_campaign_fee_original (
  organisation_id text NOT NULL,
  campaign_id uuid NOT NULL,
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
  PRIMARY KEY (organisation_id, campaign_id, loan_id, fee_type),
  FOREIGN KEY (organisation_id, campaign_id, loan_id)
    REFERENCES lms.collection_campaign_application (organisation_id, campaign_id, loan_id)
);

COMMENT ON TABLE lms.collection_campaign_fee_original IS
  'Contractual fee in integer cents, stored separately from the campaign reduction.';

CREATE TABLE lms.collection_campaign_instalment (
  organisation_id text NOT NULL,
  campaign_id uuid NOT NULL,
  loan_id uuid NOT NULL,
  sequence integer NOT NULL CHECK (sequence > 0),
  due_on date NOT NULL,
  principal_cents bigint NOT NULL CHECK (principal_cents > 0),
  skipped boolean NOT NULL DEFAULT false,
  PRIMARY KEY (organisation_id, campaign_id, loan_id, sequence),
  FOREIGN KEY (organisation_id, campaign_id, loan_id)
    REFERENCES lms.collection_campaign_application (organisation_id, campaign_id, loan_id)
);

COMMENT ON TABLE lms.collection_campaign_instalment IS
  'Copy of the contractual instalment. skipped marks a payment holiday. The schedule_line row is not updated, and principal_cents is not a new instalment.';

CREATE INDEX collection_campaign_application_loan
  ON lms.collection_campaign_application (organisation_id, loan_id);
