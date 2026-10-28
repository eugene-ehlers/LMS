"""Refresh the holiday block in db/seed/001_reference.sql.

The dates come from lms_config.calendar.public_holidays, which follows the
Public Holidays Act schedule and the Sunday observance rule. Presidential
one-off holidays are inserted as source = 'presidential' and are not
produced here.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lms_config.calendar import public_holidays

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "db" / "seed" / "001_reference.sql"
MARKER = "-- HOLIDAYS 2026-2032\n"


def render() -> str:
    lines = [
        MARKER,
        "-- generated from lms_config.calendar.public_holidays; do not edit by hand\n",
        "INSERT INTO lms.ref_public_holiday (holiday_date, name, source) VALUES\n",
    ]
    rows: list[str] = []
    for year in range(2026, 2033):
        for day, name, source in public_holidays(year):
            safe_name = name.replace("'", "''")
            rows.append(f"  ('{day.isoformat()}', '{safe_name}', '{source}')")
    lines.append(",\n".join(rows))
    lines.append(";\n")
    return "".join(lines)


def main() -> None:
    text = SEED.read_text()
    if MARKER not in text:
        raise SystemExit(f"marker not found in {SEED}")
    head = text.split(MARKER, 1)[0]
    SEED.write_text(head + render())


if __name__ == "__main__":
    main()
