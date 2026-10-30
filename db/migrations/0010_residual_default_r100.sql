-- Decision 19. The residual platform default is R100 (10 000 cents).
-- The column stays nullable. resolve_residual_threshold_cents fills R100
-- when the organisation and the product are both null.

COMMENT ON COLUMN lms.cfg_organisation_settings.residual_write_off_threshold_cents IS
  'Decisions 8 and 19. Cents. Null fills the platform default of 10000 (R100) in resolve_residual_threshold_cents. The column itself has no default.';

COMMENT ON COLUMN lms.cfg_product_terms.residual_write_off_threshold_cents IS
  'Decision 19 product override. Null inherits the organisation. When both are null, resolve_residual_threshold_cents fills 10000 (R100).';
