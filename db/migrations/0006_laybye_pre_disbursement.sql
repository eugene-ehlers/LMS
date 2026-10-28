-- A parent may exist before the loan is granted so pre-disbursement
-- receipts can sit in the Laybye child. The disbursement value date is
-- unknown until grant. LOCKED_DECISIONS §4.
--
-- contractual_end >= disbursement_value_date stays. In PostgreSQL a NULL
-- disbursement date makes that comparison unknown, and a CHECK treats
-- unknown as success.

ALTER TABLE lms.loan_account
  ALTER COLUMN disbursement_value_date DROP NOT NULL;

COMMENT ON COLUMN lms.loan_account.disbursement_value_date IS
  'Null until the loan is granted. Cash in on the Laybye child is not a loan-out. LOCKED_DECISIONS §4.';
