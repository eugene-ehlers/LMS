-- Statement disclosure for one Enigma organisation id.
-- Locked decision 15 stores only the opaque organisation id as identity.
-- These columns are the LMS configuration the statements layer is instructed
-- to read. They are not an Enigma organisation record. A blank required
-- column fails closed in lms_config.compliance. Trading name may be blank
-- (regulation 35(a)(ii): "if any").

CREATE TABLE lms.cfg_provider_compliance (
  organisation_id uuid PRIMARY KEY,
  legal_name text NOT NULL,
  ncr_registration_number text NOT NULL,
  trading_name text NOT NULL DEFAULT '',
  physical_address text NOT NULL,
  postal_address text NOT NULL,
  telephone text NOT NULL,
  bank_name text NOT NULL,
  bank_account_number text NOT NULL,
  branch_code text NOT NULL,
  payment_reference text NOT NULL,
  CONSTRAINT compliance_required CHECK (
    length(btrim(legal_name)) > 0
    AND length(btrim(ncr_registration_number)) > 0
    AND length(btrim(physical_address)) > 0
    AND length(btrim(postal_address)) > 0
    AND length(btrim(telephone)) > 0
    AND length(btrim(bank_name)) > 0
    AND length(btrim(bank_account_number)) > 0
    AND length(btrim(branch_code)) > 0
    AND length(btrim(payment_reference)) > 0
  )
);

COMMENT ON TABLE lms.cfg_provider_compliance IS
  'Provider disclosure for statements. Read by the statements layer. Not Enigma. Locked decision 15 conflict is in docs/statements/implementation-note.md.';
