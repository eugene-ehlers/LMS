-- Decisions 6, 8 and 19. In-duplum trigger and residual write-off threshold.
-- Organisation row, optional product override.
-- in_duplum_trigger has no default: null fails closed at booking.
-- residual_write_off_threshold_cents has no column default. Null means the
-- resolver fills the decision 8 amount of R100 (10 000 cents).
-- A stored zero is a client choice, not the R100 default.

SET TIME ZONE 'UTC';

ALTER TABLE lms.cfg_organisation_settings
  ADD COLUMN in_duplum_trigger text
    CHECK (
      in_duplum_trigger IS NULL
      OR in_duplum_trigger IN ('contractual_breach', 'collections_default')
    ),
  ADD COLUMN residual_write_off_threshold_cents integer
    CHECK (
      residual_write_off_threshold_cents IS NULL
      OR residual_write_off_threshold_cents >= 0
    );

COMMENT ON COLUMN lms.cfg_organisation_settings.in_duplum_trigger IS
  'Decisions 6 and 19. contractual_breach or collections_default. Null fails closed at booking. There is no platform default.';

COMMENT ON COLUMN lms.cfg_organisation_settings.residual_write_off_threshold_cents IS
  'Decisions 8 and 19. Cents. Null is the platform default of 10000 (R100), applied by resolve_residual_threshold_cents. The column itself has no default.';

ALTER TABLE lms.cfg_product_terms
  ADD COLUMN in_duplum_trigger text
    CHECK (
      in_duplum_trigger IS NULL
      OR in_duplum_trigger IN ('contractual_breach', 'collections_default')
    ),
  ADD COLUMN residual_write_off_threshold_cents integer
    CHECK (
      residual_write_off_threshold_cents IS NULL
      OR residual_write_off_threshold_cents >= 0
    );

COMMENT ON COLUMN lms.cfg_product_terms.in_duplum_trigger IS
  'Decision 19 product override. Null inherits the organisation.';

COMMENT ON COLUMN lms.cfg_product_terms.residual_write_off_threshold_cents IS
  'Decision 19 product override. Null inherits the organisation. When both are null, resolve_residual_threshold_cents fills 10000 (R100).';
