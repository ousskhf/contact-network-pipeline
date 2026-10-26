"""Manual outreach tracking (status, dates, notes...), kept apart from the warehouse.

Stored in its own DuckDB file ($CNP_OUTREACH, default data/outreach.duckdb) as long-format rows
(phone, field, value), so rebuilding cnp.duckdb or re-running the pipeline never erases it. An
entry is keyed by the phone it was saved under and matches a tracker row through ANY of that
person's numbers, so it survives re-exports and re-ordered numbers. This file is the one dataset
that cannot be regenerated from raw exports: back it up.
"""
import os
from pathlib import Path

import duckdb
import pandas as pd

from ingest import locations

DATE_FIELDS = ["Date de Premier Contact", "Date de Dernier Contact", "Date de Relance", "Date de Conversion"]
MAIN_FIELDS = ["Statut", *DATE_FIELDS, "Contacté Par", "Type d'Intérêt", "Produit d'Intérêt", "Notes"]
MORE_FIELDS = ["Genre", "Langue Préférée", "Comment Connu(e)", "Recommandé Par", "Famille",
               "Tranche d'Âge", "Objection/Raison", "Réseau social"]
FIELDS = MAIN_FIELDS + MORE_FIELDS
# Contact data that comes from the phone export; a stored value overrides it (set by the Sheet sync).
LOCATION_FIELDS = ["Pays", "Région", "Ville", "Localité", "Adresse"]      # Ville/Région split in five levels, wide to precise
CONTACT_FIELDS = [*LOCATION_FIELDS, "Email", "Profession"]
# Fields renamed over time, applied once each, in order (a town was first "Ville/Région", then "Localité", then "Ville";
# "Localité" now means the neighbourhood, so it must not be moved again).
RENAMED_FIELDS = [("Ville/Région", "Localité"), ("Localité", "Ville")]
ALLOWED = FIELDS + CONTACT_FIELDS
PHONE_COLS = ["Téléphone", "Téléphone 2", "Téléphone 3", "Autres numéros"]
ARCHIVED = "Archivé"      # ignored by the app and dashboard, kept in the Sheet, restorable by changing the status
STATUTS = ["À contacter", "Contacté", "Intéressé", "À relancer", "Converti", "Pas intéressé", ARCHIVED]


def default_path() -> str:
    return os.environ.get("CNP_OUTREACH", "data/outreach.duckdb")


def migrate(con) -> None:
    """Move entries stored under a renamed field to its new name, once per table (a value already stored there wins)."""
    con.execute("create table if not exists migrations (id varchar primary key)")
    done = {r[0] for r in con.execute("select id from migrations").fetchall()}
    for table in ("outreach", "sheet_base"):
        if not con.execute("select count(*) from information_schema.tables where table_name = ?", [table]).fetchone()[0]:
            continue                                 # created later; _state() calls migrate again
        for old, new in RENAMED_FIELDS:
            mark = f"{old}>{new}:{table}"
            if mark in done:
                continue
            con.execute(f"insert into {table} select phone, ?, value from {table} o where field = ? and not exists "
                        f"(select 1 from {table} n where n.phone = o.phone and n.field = ?)", [new, old, new])
            con.execute(f"delete from {table} where field = ?", [old])
            con.execute("insert into migrations values (?)", [mark])
        mark = f"ville-without-region:{table}"       # "Ariana - Soukra" -> "Soukra"
        if mark not in done:
            for phone, value in con.execute(f"select phone, value from {table} where field = 'Ville'").fetchall():
                plain = locations.strip_region(value)
                if plain != value:
                    con.execute(f"update {table} set value = ? where phone = ? and field = 'Ville'", [plain, phone])
            con.execute("insert into migrations values (?)", [mark])


def _connect(path=None):
    path = path or default_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(path)
    con.execute("create table if not exists outreach (phone varchar, field varchar, value varchar, "
                "primary key (phone, field))")
    migrate(con)
    return con


def load(path=None) -> pd.DataFrame:
    """Long format: phone, field, value."""
    path = path or default_path()
    if not Path(path).exists():
        return pd.DataFrame(columns=["phone", "field", "value"])
    con = _connect(path)
    try:
        return con.execute("select phone, field, value from outreach").df()
    finally:
        con.close()


def save(changes: dict, path=None) -> int:
    """changes: {phone: {field: value}}. Replaces that phone's entries for FIELDS and for any contact field
    passed; contact overrides not mentioned are kept. Empty values are not stored."""
    con = _connect(path)
    try:
        for phone, fields in changes.items():
            replaced = set(FIELDS) | (set(fields) & set(CONTACT_FIELDS))
            marks = ", ".join("?" for _ in replaced)
            con.execute(f"delete from outreach where phone = ? and field in ({marks})", [phone, *replaced])
            rows = [(phone, f, str(v)) for f, v in fields.items()
                    if f in ALLOWED and v is not None and str(v).strip() not in ("", "NaT", "nan", "None")]
            if rows:
                con.executemany("insert into outreach values (?, ?, ?)", rows)
        return len(changes)
    finally:
        con.close()


NETWORK_NOTE = "Importé du réseau"          # Notes prefix of rows that exist only in the referral network


def is_network_row(row) -> bool:
    note = row.get("Notes")
    return isinstance(note, str) and note.startswith(NETWORK_NOTE)


def _network_suffix(row) -> str:
    """user_id (the source system's stable member id) when the row has one, else the lowercased name as a fallback
    (older stored rows, or a row built without it) -- user_id survives a retyped/recapitalised name,
    name does not."""
    uid = row.get("user_id")
    if uid is not None and uid is not pd.NA and not (isinstance(uid, float) and pd.isna(uid)):
        try:
            return str(int(float(uid)))
        except (TypeError, ValueError):
            pass
    return str(row.get("Nom") or "").strip().lower()


def row_key(row) -> str:
    """Key an entry is stored under: the phone, or phone#<user_id> for network-only members (members of
    the network can share one phone, e.g. a sponsor's, so the phone alone would mix their entries up)."""
    if is_network_row(row):
        return f"{row.get('Téléphone')}#{_network_suffix(row)}"
    return row.get("Téléphone")


def numbers(row) -> list[str]:
    if is_network_row(row):
        return [row_key(row)]
    out = []
    for col in PHONE_COLS:
        v = row.get(col)
        if isinstance(v, str) and v:
            out += [n.strip() for n in v.split(" ; ") if n.strip()]
    return out


def overlay(tracker: pd.DataFrame, stored: pd.DataFrame, notes_column: str = "Notes") -> tuple[pd.DataFrame, int]:
    """Fill the tracker's outreach columns from stored entries. Returns (df, orphan count).

    Stored notes are appended to "Notes" by default; with another notes_column they go into that
    separate column instead (used by the dashboard editor)."""
    df = tracker.copy()
    if notes_column != "Notes":
        df[notes_column] = ""
    index = {}
    for i, row in enumerate(df.to_dict("records")):
        for n in numbers(row):
            index.setdefault(n, i)
    orphans = 0
    for phone, grp in stored.groupby("phone"):
        i = index.get(phone)
        if i is None:
            orphans += 1
            continue
        for field, value in zip(grp["field"], grp["value"]):
            if field == "Notes":                       # keep the import/alias note, add yours
                col = df.columns.get_loc(notes_column)
                old = df.iat[i, col]
                old = old if isinstance(old, str) and old else ""
                df.iat[i, col] = f"{old}\n{value}".strip()
            elif field in df.columns:
                df.iat[i, df.columns.get_loc(field)] = value
    return df, orphans


def norm(v) -> str:
    if v is None or v is pd.NaT or (isinstance(v, float) and pd.isna(v)):
        return ""
    return v.isoformat() if hasattr(v, "isoformat") else str(v).strip()


def collect_changes(edited: pd.DataFrame, original: pd.DataFrame, current: pd.DataFrame,
                    phones: pd.Series, fields: list[str]) -> dict:
    """Rows whose editable fields differ from what was shown, as {phone: full field dict}.

    `current` holds every stored field (also those not on screen) so saving never wipes them.
    """
    changes = {}
    for idx in edited.index:
        new = {f: norm(edited.at[idx, f]) for f in fields}
        if new != {f: norm(original.at[idx, f]) for f in fields}:
            full = {f: norm(current.at[idx, f]) for f in FIELDS}
            full.update(new)
            changes[phones.at[idx]] = full
    return changes


def rekey_network_only_to_user_id(tracker: pd.DataFrame, path=None, apply: bool = False) -> dict:
    """One-time migration: move a network-only member's stored rows from the old "phone#name" key to
    "phone#user_id" now that user_id is available (stable across a retyped/recapitalised name, unlike
    name). Safe by construction, same as rekey_linked_members: only moves a key that still identifies
    the same tracker row under its new form, never overwrites a field the target already has, and
    deletes the old rows only once every field is copied. With apply=False nothing is written.
    `tracker` is the tracker_export frame (not overlaid), with a "user_id" column."""
    path = path or default_path()
    if not Path(path).exists():
        return {"moved": 0, "unchanged": 0, "conflicts": 0, "no_user_id": 0}
    by_old_key: dict[str, str] = {}
    for row in tracker.to_dict("records"):
        if not is_network_row(row):
            continue
        name_key = f"{row.get('Téléphone')}#{str(row.get('Nom') or '').strip().lower()}"
        new_key = row_key(row)
        if new_key != name_key:
            by_old_key[name_key] = new_key
    stats = {"moved": 0, "unchanged": 0, "conflicts": 0, "no_user_id": 0}
    con = duckdb.connect(path, read_only=not apply)
    try:
        con.execute("begin")
        for table in ("outreach", "sheet_base", "sheet_extra"):
            if not con.execute("select count(*) from information_schema.tables where table_name = ?", [table]).fetchone()[0]:
                continue
            for (old_key,) in con.execute(f"select distinct phone from {table} where phone like '%#%'").fetchall():
                new_key = by_old_key.get(old_key)
                if new_key is None:
                    stats["no_user_id"] += 1
                    continue
                old = con.execute(f"select field, value from {table} where phone = ?", [old_key]).fetchall()
                have = dict(con.execute(f"select field, value from {table} where phone = ?", [new_key]).fetchall())
                if any(f in have and have[f] != v for f, v in old):
                    stats["conflicts"] += 1
                    continue
                if table == "outreach":
                    stats["moved"] += 1
                if apply:
                    con.executemany(f"insert into {table} select ?, ?, ? where not exists "
                                    f"(select 1 from {table} where phone = ? and field = ?)",
                                    [(new_key, f, v, new_key, f) for f, v in old])
                    con.execute(f"delete from {table} where phone = ?", [old_key])
        con.execute("commit" if apply else "rollback")
    except Exception:
        con.execute("rollback")
        raise
    finally:
        con.close()
    return stats


def rekey_linked_members(tracker: pd.DataFrame, path=None, apply: bool = False) -> dict:
    """Move entries stored under "phone#name" (a network-only member) to the phone key of the contact
    that member has since become, so a member added to the phone contacts keeps their status and notes.

    Safe by construction: an entry is moved only when exactly one contact row matches (a shared phone is
    disambiguated by name), a field the contact already has is never overwritten, and the old rows are
    deleted only once every one of their fields is copied. Anything else is left and counted.
    With apply=False nothing is written. `tracker` is the tracker_export frame (not overlaid)."""
    path = path or default_path()
    if not Path(path).exists():
        return {"moved": 0, "ambiguous": 0, "conflicts": 0, "still_network": 0}
    rows = tracker.to_dict("records")
    live = {row_key(r) for r in rows if is_network_row(r)}
    by_number: dict[str, list[dict]] = {}
    for r in rows:
        if not is_network_row(r):
            for n in numbers(r):
                by_number.setdefault(n, []).append(r)
    stats = {"moved": 0, "ambiguous": 0, "conflicts": 0, "still_network": 0}
    con = duckdb.connect(path, read_only=not apply)
    try:
        con.execute("begin")
        for table in ("outreach", "sheet_base", "sheet_extra"):
            if not con.execute("select count(*) from information_schema.tables where table_name = ?", [table]).fetchone()[0]:
                continue
            for (key,) in con.execute(f"select distinct phone from {table} where phone like '%#%'").fetchall():
                if key in live:
                    stats["still_network"] += 1
                    continue
                number, _, name = key.partition("#")
                found = by_number.get(number, [])
                if len(found) > 1:
                    found = [r for r in found if str(r.get("Nom") or "").strip().lower() == name]
                if len(found) != 1:
                    stats["ambiguous"] += 1
                    continue
                target = found[0].get("Téléphone")
                old = con.execute(f"select field, value from {table} where phone = ?", [key]).fetchall()
                have = dict(con.execute(f"select field, value from {table} where phone = ?", [target]).fetchall())
                if any(f in have and have[f] != v for f, v in old):
                    stats["conflicts"] += 1
                    continue
                if table == "outreach":
                    stats["moved"] += 1
                if apply:
                    con.executemany(f"insert into {table} select ?, ?, ? where not exists "
                                    f"(select 1 from {table} where phone = ? and field = ?)",
                                    [(target, f, v, target, f) for f, v in old])
                    con.execute(f"delete from {table} where phone = ?", [key])
        con.execute("commit" if apply else "rollback")
    except Exception:
        con.execute("rollback")
        raise
    finally:
        con.close()
    return stats
