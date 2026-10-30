-- Decision 8 and Decision 19. Comment correction only.
-- The residual platform default is R100 (10 000 cents).
-- Booking fails closed when the in-duplum trigger is unset.
-- CHECK constraints are unchanged.

SET TIME ZONE 'UTC';

COMMENT ON COLUMN lms.cfg_organisation_settings.in_duplum_trigger IS
  'Decisions 6 and 19. contractual_breach or collections_default. Null fails closed at booking. There is no platform default.';

COMMENT ON COLUMN lms.cfg_organisation_settings.residual_write_off_threshold_cents IS
  'Decisions 8 and 19. Cents. Null is the platform default of 10000 (R100), applied by resolve_residual_threshold_cents. The column itself has no default. A stored zero is a client choice.';

COMMENT ON COLUMN lms.cfg_product_terms.residual_write_off_threshold_cents IS
  'Decision 19 product override. Null inherits the organisation. When both are null, resolve_residual_threshold_cents fills 10000 (R100).';
