"""Load a Google Contacts CSV export into raw.contacts, untouched (all text)."""
import duckdb


def load_contacts(con: duckdb.DuckDBPyConnection, path: str) -> int:
    con.execute("create schema if not exists raw")
    con.execute(
        "create or replace table raw.contacts as "
        "select row_number() over () as source_row, * "
        "from read_csv(?, header=true, all_varchar=true)",
        [path],
    )
    for column in ("Address 1 - City", "Address 1 - Region", "Address 1 - Street", "Address 1 - Country"):
        have = {r[0] for r in con.execute("describe raw.contacts").fetchall()}
        if column not in have:                       # exports without any address still feed the address columns
            con.execute(f'alter table raw.contacts add column "{column}" varchar')
    return con.execute("select count(*) from raw.contacts").fetchone()[0]
