"""Write the tracker sheet (dbt model tracker_export) to $CNP_EXPORT as CSV, ready to import into Sheets.

Manual outreach entries (ingest/outreach.py) are overlaid, so re-importing never loses them.
"""
import os
from pathlib import Path

import duckdb

from ingest import outreach


def export(db: str, out: str, outreach_path: str | None = None) -> int:
    con = duckdb.connect(db, read_only=True)
    df = con.execute("select * exclude (sort_key) from main.tracker_export order by sort_key").df()
    con.close()
    df, orphans = outreach.overlay(df, outreach.load(outreach_path))
    if orphans:
        print(f"warning: {orphans} outreach entr{'y' if orphans == 1 else 'ies'} match no current contact")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return len(df)


if __name__ == "__main__":
    out = os.environ.get("CNP_EXPORT", "data/contact_tracker.csv")
    print(f"{export(os.environ.get('CNP_DB', 'data/cnp.duckdb'), out)} rows -> {out}")
