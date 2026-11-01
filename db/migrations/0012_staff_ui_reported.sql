-- STAFF_UI_REPORTED is already accepted by the in-process audit log.
-- This row lets a database insert of that code succeed. Do not renumber
-- 0008 through 0011.

SET TIME ZONE 'UTC';

INSERT INTO lms.ref_audit_event_type (code, category)
VALUES ('STAFF_UI_REPORTED', 'operational')
ON CONFLICT (code) DO NOTHING;
