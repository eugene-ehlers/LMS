-- Day-1 in-duplum clip. The warning is operational. Amounts stay in the
-- payload as integer cents. This file does not change the ceiling.

SET TIME ZONE 'UTC';

INSERT INTO lms.ref_audit_event_type (code, category)
VALUES ('IN_DUPLUM_CEILING', 'operational')
ON CONFLICT (code) DO NOTHING;
