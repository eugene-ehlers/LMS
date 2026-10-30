-- Layer 2. Campaigns, decision-19 fall-away elections, operational ceilings,
-- and the audit event types the staff commands append.
-- Amounts are integer cents. Rates are fractions (0.05 = 5%).
-- Recognition dates are Johannesburg calendar dates. The column is `date`.
-- This migration does not reprice lms.election_snapshot and does not change
-- statement tables.

SET TIME ZONE 'UTC';

ALTER TABLE lms.cfg_organisation_settings
  ADD COLUMN campaign_fall_away_choice text
    CHECK (
      campaign_fall_away_choice IS NULL
      OR campaign_fall_away_choice IN ('falls_away_on_default', 'does_not_fall_away')
    ),
  ADD COLUMN campaign_fall_away_trigger text
    CHECK (
      campaign_fall_away_trigger IS NULL
      OR campaign_fall_away_trigger IN ('contractual_breach', 'collections_default')
    );

ALTER TABLE lms.cfg_organisation_settings
  ADD CONSTRAINT organisation_fall_away_pair CHECK (
    (
      campaign_fall_away_choice IS NULL
      AND campaign_fall_away_trigger IS NULL
    )
    OR (
      campaign_fall_away_choice = 'does_not_fall_away'
      AND campaign_fall_away_trigger IS NULL
    )
    OR (
      campaign_fall_away_choice = 'falls_away_on_default'
      AND campaign_fall_away_trigger IS NOT NULL
    )
  );

COMMENT ON COLUMN lms.cfg_organisation_settings.campaign_fall_away_choice IS
  'Decision 19. falls_away_on_default or does_not_fall_away. Null fails closed. The same choice is also stored on each campaign. Which value wins when they differ is an open point in LOCKED_DECISIONS.';

COMMENT ON COLUMN lms.cfg_organisation_settings.campaign_fall_away_trigger IS
  'Decision 19. contractual_breach or collections_default, and only when the choice is falls_away_on_default.';

ALTER TABLE lms.cfg_product_terms
  ADD COLUMN campaign_fall_away_choice text
    CHECK (
      campaign_fall_away_choice IS NULL
      OR campaign_fall_away_choice IN ('falls_away_on_default', 'does_not_fall_away')
    ),
  ADD COLUMN campaign_fall_away_trigger text
    CHECK (
      campaign_fall_away_trigger IS NULL
      OR campaign_fall_away_trigger IN ('contractual_breach', 'collections_default')
    );

ALTER TABLE lms.cfg_product_terms
  ADD CONSTRAINT product_fall_away_pair CHECK (
    (
      campaign_fall_away_choice IS NULL
      AND campaign_fall_away_trigger IS NULL
    )
    OR (
      campaign_fall_away_choice = 'does_not_fall_away'
      AND campaign_fall_away_trigger IS NULL
    )
    OR (
      campaign_fall_away_choice = 'falls_away_on_default'
      AND campaign_fall_away_trigger IS NOT NULL
    )
  );

COMMENT ON COLUMN lms.cfg_product_terms.campaign_fall_away_choice IS
  'Decision 19 product override. Null inherits the organisation pair, choice and trigger together.';

COMMENT ON COLUMN lms.cfg_product_terms.campaign_fall_away_trigger IS
  'Decision 19 product override. Null when the product choice is null or does_not_fall_away.';

-- Decision 3 allows a discount above the base. The net is floored at 0%.
-- The older product-terms check discount_rate <= base_rate is not copied here.
CREATE TABLE lms.cfg_campaign (
  campaign_id uuid PRIMARY KEY,
  organisation_id text NOT NULL CHECK (length(btrim(organisation_id)) > 0),
  product_id text CHECK (product_id IS NULL OR length(btrim(product_id)) > 0),
  start_date date NOT NULL,
  end_date date NOT NULL,
  base_rate numeric(18, 8) NOT NULL CHECK (base_rate >= 0),
  discount_rate numeric(18, 8) NOT NULL CHECK (discount_rate >= 0),
  fall_away_choice text NOT NULL
    CHECK (fall_away_choice IN ('falls_away_on_default', 'does_not_fall_away')),
  fall_away_trigger text
    CHECK (
      fall_away_trigger IS NULL
      OR fall_away_trigger IN ('contractual_breach', 'collections_default')
    ),
  initiation_fee_discount_cents integer NOT NULL DEFAULT 0
    CHECK (initiation_fee_discount_cents >= 0),
  service_fee_discount_cents integer NOT NULL DEFAULT 0
    CHECK (service_fee_discount_cents >= 0),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  CONSTRAINT campaign_dates CHECK (start_date <= end_date),
  CONSTRAINT campaign_fall_away_pair CHECK (
    (
      fall_away_choice = 'does_not_fall_away'
      AND fall_away_trigger IS NULL
    )
    OR (
      fall_away_choice = 'falls_away_on_default'
      AND fall_away_trigger IS NOT NULL
    )
  )
);

COMMENT ON TABLE lms.cfg_campaign IS
  'Decision 3. A loan whose Johannesburg recognition date is inside start_date and end_date qualifies, including when the loan term runs past end_date. Editing or ending a row does not update a booked agreement.';

CREATE TABLE lms.cfg_rand_ceiling (
  scope text NOT NULL CHECK (scope IN ('platform', 'company')),
  action text NOT NULL CHECK (length(btrim(action)) > 0),
  amount_cents integer NOT NULL CHECK (amount_cents >= 0),
  currency character(3) NOT NULL DEFAULT 'ZAR' CHECK (currency = 'ZAR'),
  organisation_id text NOT NULL DEFAULT '',
  version integer NOT NULL CHECK (version > 0),
  PRIMARY KEY (scope, action, organisation_id),
  CONSTRAINT ceiling_scope_organisation CHECK (
    (scope = 'platform' AND organisation_id = '')
    OR (scope = 'company' AND length(btrim(organisation_id)) > 0)
  )
);

COMMENT ON TABLE lms.cfg_rand_ceiling IS
  'Decision 22. Authorization limits in cents. LMS applies the lower of the platform row and the company row. A missing platform row stops the command. Not an NCA maximum.';

-- The rate and the credit-life premium are stored as supplied.
-- campaign_* is a copy taken at intake. A later campaign edit does not update it.
CREATE TABLE lms.decision_intake (
  intake_id uuid PRIMARY KEY,
  organisation_id text NOT NULL CHECK (length(btrim(organisation_id)) > 0),
  product_id text CHECK (product_id IS NULL OR length(btrim(product_id)) > 0),
  application_number text NOT NULL CHECK (length(btrim(application_number)) > 0),
  recognition_date date NOT NULL,
  supplied_rate numeric(18, 8) NOT NULL CHECK (supplied_rate >= 0),
  credit_life_premium_cents integer NOT NULL CHECK (credit_life_premium_cents >= 0),
  campaign_id uuid,
  campaign_base_rate numeric(18, 8) CHECK (campaign_base_rate IS NULL OR campaign_base_rate >= 0),
  campaign_discount_rate numeric(18, 8) CHECK (campaign_discount_rate IS NULL OR campaign_discount_rate >= 0),
  campaign_net_rate numeric(18, 8) CHECK (campaign_net_rate IS NULL OR campaign_net_rate >= 0),
  campaign_fall_away_choice text,
  campaign_fall_away_trigger text,
  maturity_date date
);

COMMENT ON TABLE lms.decision_intake IS
  'Decision 13. supplied_rate and credit_life_premium_cents are the decision-engine figures, unchanged. The campaign copy is not written back onto the campaign, and it is not a substitute for the supplied rate. That substitution is an open point.';

INSERT INTO lms.ref_audit_event_type (code, category) VALUES
  ('CAMPAIGN_CREATED', 'operational'),
  ('CAMPAIGN_EDITED', 'operational'),
  ('CAMPAIGN_ENDED', 'operational'),
  ('ELECTION_CHANGED', 'operational'),
  ('COMPLIANCE_CHANGED', 'operational'),
  ('CEILING_CHANGED', 'operational'),
  ('DECISION_INTAKE_STORED', 'operational');

GRANT SELECT, INSERT, UPDATE ON lms.cfg_campaign TO lms_app;
GRANT SELECT, INSERT, UPDATE ON lms.cfg_rand_ceiling TO lms_app;
GRANT SELECT, INSERT ON lms.decision_intake TO lms_app;
GRANT SELECT ON lms.cfg_campaign, lms.cfg_rand_ceiling, lms.decision_intake TO lms_reader;
