-- Settlement re-advance. The outcome row is operational: the receipt amount
-- stays on the payment audit. This file does not choose a rate, a term,
-- or an instalment.

SET TIME ZONE 'UTC';

INSERT INTO lms.ref_audit_event_type (code, category)
VALUES ('SETTLEMENT_READVANCE', 'operational')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS lms.settlement_readvance (
  organisation_id text NOT NULL,
  readvance_id uuid NOT NULL,
  settled_agreement_id text NOT NULL,
  settled_loan_id text NOT NULL,
  settled_loan_number text,
  new_agreement_id text NOT NULL,
  new_loan_id text NOT NULL,
  new_loan_number text NOT NULL,
  new_application_number text NOT NULL,
  short_term_rate_flag text
    CHECK (
      short_term_rate_flag IS NULL
      OR short_term_rate_flag IN ('five_percent', 'three_percent')
    ),
  supplied_rate numeric(12, 8) NOT NULL CHECK (supplied_rate >= 0),
  contractual_instalment_cents bigint NOT NULL CHECK (contractual_instalment_cents >= 0),
  term_count integer NOT NULL CHECK (term_count > 0),
  payment_frequency text NOT NULL,
  campaign_fall_away_choice text NOT NULL
    CHECK (campaign_fall_away_choice IN ('falls_away_on_default', 'does_not_fall_away')),
  campaign_fall_away_trigger text
    CHECK (
      campaign_fall_away_trigger IS NULL
      OR campaign_fall_away_trigger IN ('contractual_breach', 'collections_default')
    ),
  recognition_date date NOT NULL,
  receipt_cents bigint NOT NULL CHECK (receipt_cents > 0),
  PRIMARY KEY (organisation_id, readvance_id),
  UNIQUE (organisation_id, settled_agreement_id),
  UNIQUE (organisation_id, new_agreement_id),
  UNIQUE (organisation_id, new_application_number)
);

COMMENT ON TABLE lms.settlement_readvance IS
  'Links the loan booked from the decision engine to the agreement settled in the same command. The in-process store is what this layer writes. The table is the shape for a database deployment.';
