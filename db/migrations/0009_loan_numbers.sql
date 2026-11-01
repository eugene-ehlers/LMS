-- Decision 25. The LMS assigns the loan number. The application number is
-- supplied and stored for the audit link. A lay-by child keeps the parent's
-- loan number; instrument_kind is the other indicator. The number is an
-- 18-digit zero-padded sequence per organisation so it does not run out.
-- Company letters and the month and year may be included; this column does
-- not require them. Existing rows stay null: this file does not invent numbers
-- for loans booked before the column existed.

ALTER TABLE lms.loan_account
  ADD COLUMN loan_number text,
  ADD COLUMN application_number text;

ALTER TABLE lms.loan_account
  ADD CONSTRAINT loan_number_digits CHECK (
    loan_number IS NULL OR loan_number ~ '^[0-9]{18}$'
  );

CREATE UNIQUE INDEX loan_number_one_parent
  ON lms.loan_account (organisation_id, loan_number)
  WHERE instrument_kind = 'loan';

CREATE UNIQUE INDEX application_one_loan
  ON lms.loan_account (organisation_id, application_number)
  WHERE instrument_kind = 'loan' AND application_number IS NOT NULL AND btrim(application_number) <> '';

CREATE TABLE lms.loan_number_sequence (
  organisation_id text PRIMARY KEY,
  last_number bigint NOT NULL CHECK (last_number >= 0)
);

COMMENT ON COLUMN lms.loan_account.loan_number IS
  'LMS-generated sequential number. The lay-by child stores the same value. LOCKED_DECISIONS §25.';

COMMENT ON TABLE lms.loan_number_sequence IS
  'Last assigned loan number for one organisation. The next number is last_number + 1. Numbers are not skipped.';
