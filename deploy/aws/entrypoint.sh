#!/bin/sh
# Apply the repository migrations, then serve the LMS.
set -eu
python -m lms.migrate
exec python -m lms.staff_ui
