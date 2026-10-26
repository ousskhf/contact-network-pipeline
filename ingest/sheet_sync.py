"""Two-way sync between the shared tracker Sheet (Google Sheets) and the pipeline.

Every person is in the Sheet: the contacts and the network members who are not in the contacts.
Rows are matched by normalised phone number (digits only, leading zeros dropped, because Sheets strips
them); network-only members also use their name, since members can share a phone. Per cell, the last synced
value is the base:
  only the Sheet changed      -> the Sheet value is stored in outreach.duckdb
  only the dashboard changed  -> the value is written to the Sheet
  both changed                -> the Sheet wins (it is the shared copy) and the conflict is reported
Name, phones and the import notes belong to the pipeline and are never read back; Grade and Actif come
from the source system and are always overwritten in the Sheet. Columns added in the Sheet are kept in
outreach.duckdb (table sheet_extra) but not shown in the dashboard. People new to the pipeline are
appended; rows typed by hand in the Sheet are left alone and counted.

Setup: a Google service account with the Sheets API enabled, its JSON key in $CNP_GOOGLE_CREDENTIALS
(default data/google-service-account.json, gitignored), the Sheet shared with its e-mail as editor, and the
Sheet id in $CNP_SHEET_ID. Without them the sync is skipped.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from ingest import locations, outreach

NOTES_HEADER = "Notes perso"                       # Sheet header for the personal notes (outreach field "Notes")
ID_HEADER = "ID Membre"                            # Sheet header for the network member's stable id (see sync_key)
# network data: the pipeline value always overwrites the Sheet. ID_HEADER is written like the rest, so a
# network-only row's identity survives a retyped/recapitalised name on the next sync (see sync_key).
PIPELINE_COLUMNS = ["Grade", "Actif", "Sponsor", "Directs", "Profondeur",
                     "CA Personnel Terminé", "CA Personnel En Attente",
                     "CA Équipe Terminé", "CA Équipe En Attente",
                     "Objectif Grade", "Taux Bonus", "Grade Suivant", ID_HEADER]
PIPELINE_RENAMES = {ID_HEADER: "user_id"}           # Sheet header -> tracker/current dataframe column, where they differ
READ_ONLY = {"Nom", "Téléphone", "Téléphone 2", "Téléphone 3", "Autres numéros", "Notes", *PIPELINE_COLUMNS}
SYNCED = [NOTES_HEADER if f == "Notes" else f for f in outreach.ALLOWED]


def phone_key(value) -> str:
    return re.sub(r"\D", "", str(value or "")).lstrip("0")


def _id_suffix(name, user_id) -> str:
    """user_id (the source system's stable member id) when present, else the lowercased name as a fallback (a Sheet row
    the pipeline hasn't written ID_HEADER to yet, or older stored data) -- see outreach._network_suffix."""
    has_id = user_id is not None and user_id is not pd.NA and not (isinstance(user_id, float) and pd.isna(user_id))
    if has_id:
        s = str(user_id).strip()
        if s and s.lower() != "nan":
            try:
                return str(int(float(s)))
            except (TypeError, ValueError):
                pass
    return str(name or "").strip().lower()


def sync_key(phone, name, notes, user_id=None) -> str:
    """Identity of a row: its normalised phone; network-only members (which can share a phone) add their
    stable user_id, or their name when no user_id is known yet."""
    key = phone_key(phone)
    if str(notes or "").startswith(outreach.NETWORK_NOTE):
        return f"{key}#{_id_suffix(name, user_id)}"
    return key


WHOLE_NUMBER_COLUMNS = {ID_HEADER, "Directs", "Profondeur"}    # pandas gives these as float (NaN-able ints)


def norm(header: str, value) -> str:
    # value can be a nullable pandas extension type (pd.NA) for an integer column with nulls
    # (e.g. Directs, Profondeur, from duckdb's integer -> pandas Int64 conversion), not just a float NaN.
    na = value is pd.NA or (isinstance(value, float) and pd.isna(value))
    v = "" if value is None or na else str(value).strip()
    if header == "Ville":                              # old entries read "Région - Ville"
        return locations.strip_region(v)
    if header in outreach.DATE_FIELDS and v:
        t = pd.to_datetime(v, dayfirst="/" in v, errors="coerce")
        return t.date().isoformat() if pd.notna(t) else v
    if header in WHOLE_NUMBER_COLUMNS and v:
        try:
            return str(int(float(v)))
        except (TypeError, ValueError):
            pass
    return v


def merge_cell(sheet: str, local: str, base: str) -> tuple[str, str]:
    if sheet == local:
        return sheet, "same"
    if sheet == base:
        return local, "local"
    if local == base:
        return sheet, "sheet"
    return sheet, "conflict"


@dataclass
class Plan:
    cells: dict = field(default_factory=dict)        # (row, col) 1-based -> value to write in the Sheet
    appended: list = field(default_factory=list)     # new rows to append to the Sheet
    local: dict = field(default_factory=dict)        # phone key -> {header: value} to store in the pipeline
    base: dict = field(default_factory=dict)         # (phone key, header) -> value now equal on both sides
    extra: dict = field(default_factory=dict)        # (phone key, header) -> value of a column added in the Sheet
    conflicts: list = field(default_factory=list)
    sheet_only: int = 0
    duplicates: int = 0


def plan_sync(rows: list[list[str]], original: pd.DataFrame, current: pd.DataFrame, base: dict,
              fresh=frozenset()) -> Plan:
    """rows: the Sheet as read (header first). original/current: tracker rows without / with the stored
    outreach overlaid; both carry a NOTES_HEADER column and are in the same order. fresh: columns that were
    just created empty (they, and columns added below, have never been synced, so a blank cell is not a deletion)."""
    out = Plan()
    header = list(rows[0]) if rows else ["Nom", "Téléphone"]
    fresh = set(fresh)
    for h in SYNCED + PIPELINE_COLUMNS:
        if h not in header:
            header.append(h)
            fresh.add(h)
            out.cells[(1, len(header))] = h
    col = {h: i for i, h in enumerate(header)}
    custom = [h for h in header if h not in READ_ONLY and h not in SYNCED]
    col_of = lambda h: PIPELINE_RENAMES.get(h, h)      # Sheet header -> current/original dataframe column

    sheet_rows = {}
    for n, row in enumerate(rows[1:], start=2):
        at = lambda h: row[col[h]] if h in col and col[h] < len(row) else ""
        key = sync_key(at("Téléphone"), at("Nom"), at("Notes"), at(ID_HEADER))
        if not phone_key(at("Téléphone")):
            continue
        if key in sheet_rows:
            out.duplicates += 1
        else:
            sheet_rows[key] = (n, row)

    seen = set()
    for i in range(len(current)):
        key = sync_key(current["Téléphone"].iat[i], current["Nom"].iat[i], current["Notes"].iat[i],
                       current["user_id"].iat[i] if "user_id" in current.columns else None)
        if not phone_key(current["Téléphone"].iat[i]) or key in seen:
            continue
        seen.add(key)
        if key not in sheet_rows:
            out.appended.append([norm(h, current[col_of(h)].iat[i]) if col_of(h) in current.columns else ""
                                 for h in header])
            for h in SYNCED:
                if h in current.columns:
                    out.base[(key, h)] = norm(h, current[h].iat[i])
            continue
        n, row = sheet_rows[key]
        cell = lambda h: row[col[h]] if col[h] < len(row) else ""
        for h in SYNCED:
            s, d = norm(h, cell(h)), norm(h, current[h].iat[i])
            b = "" if h in fresh else base.get((key, h), norm(h, original[h].iat[i]))
            final, source = merge_cell(s, d, b)
            if final != s:
                out.cells[(n, col[h] + 1)] = final
            if final != d:
                out.local.setdefault(key, {})[h] = final
            if source == "conflict":
                out.conflicts.append((current["Nom"].iat[i], h, s, d))
            out.base[(key, h)] = final
        for h in PIPELINE_COLUMNS:
            want = norm(h, current[col_of(h)].iat[i]) if col_of(h) in current.columns else ""
            if norm(h, cell(h)) != want:
                out.cells[(n, col[h] + 1)] = want
        for h in custom:
            out.extra[(key, h)] = cell(h).strip()
    out.sheet_only = sum(1 for k in sheet_rows if k not in seen)
    return out


# --- state kept next to the outreach entries --------------------------------------------------------------

def _state(path=None):
    con = outreach._connect(path)
    for table in ("sheet_base", "sheet_extra"):
        con.execute(f"create table if not exists {table} (phone varchar, field varchar, value varchar, "
                    "primary key (phone, field))")
    outreach.migrate(con)
    return con


def load_state(path=None) -> dict:
    con = _state(path)
    try:
        return {t: {(p, f): v for p, f, v in con.execute(f"select phone, field, value from {t}").fetchall()}
                for t in ("sheet_base", "sheet_extra")}
    finally:
        con.close()


def apply_plan(plan: Plan, current: pd.DataFrame, path=None) -> None:
    """Persist what the plan decided: entries for the dashboard, the new base and the extra columns."""
    stored = outreach.load(path)
    by_phone = {}
    for phone, fld, val in zip(stored["phone"], stored["field"], stored["value"]):
        by_phone.setdefault(phone, {})[fld] = val
    uid = current["user_id"] if "user_id" in current.columns else pd.Series([None] * len(current))
    keys = {sync_key(current["Téléphone"].iat[i], current["Nom"].iat[i], current["Notes"].iat[i], uid.iat[i]): i
            for i in reversed(range(len(current)))}
    con = _state(path)
    try:
        for key, changes in plan.local.items():
            row = current.iloc[keys[key]].to_dict()
            numbers = outreach.numbers(row)
            merged = {}
            for number in numbers:
                merged.update(by_phone.get(number, {}))
                con.execute("delete from outreach where phone = ?", [number])
            for h, v in changes.items():
                merged["Notes" if h == NOTES_HEADER else h] = v
            outreach.save({outreach.row_key(row): merged}, path)
        con.execute("delete from sheet_base")
        for table, items in (("sheet_base", plan.base), ("sheet_extra", {k: v for k, v in plan.extra.items() if v})):
            if table == "sheet_extra":
                con.execute("delete from sheet_extra")
            if items:
                con.executemany(f"insert into {table} values (?, ?, ?)", [(k, h, v) for (k, h), v in items.items()])
    finally:
        con.close()


# --- one-off layout changes of the Sheet -----------------------------------------------------------------

def location_split(header: list[str]):
    """The old location column becomes Pays | Région | Ville | Localité | Adresse. It is kept (renamed Ville, so its
    values and position stay) with Pays and Région before it and Localité and Adresse after it. The anchor is the
    first-generation "Ville/Région" or, in a Sheet already split in four, the "Localité" column that held the town.
    Returns (index, columns to insert before, columns to insert after), or None when nothing is to do."""
    if "Ville" in header:
        return None
    anchor = next((h for h in ("Ville/Région", "Localité") if h in header), None)
    if anchor is None:
        return None
    return (header.index(anchor), [h for h in ("Pays", "Région") if h not in header],
            [h for h in ("Localité", "Adresse") if h == anchor or h not in header])


def ville_label_cells(rows: list[list[str]]) -> dict:
    """Ville cells still holding "Région - Ville" (the old dropdown entries): (row, column) -> the plain name."""
    header = rows[0] if rows else []
    if "Ville" not in header:
        return {}
    c = header.index("Ville")
    out = {}
    for n, row in enumerate(rows[1:], start=2):
        value = row[c] if c < len(row) else ""
        if value and locations.strip_region(value) != value:
            out[(n, c + 1)] = locations.strip_region(value)
    return out


# --- Google Sheets client ---------------------------------------------------------------------------------

class GoogleSheet:
    def __init__(self, sheet_id: str, credentials: str, tab: str | None = None):
        import gspread
        book = gspread.service_account(filename=credentials).open_by_key(sheet_id)
        self.ws = book.worksheet(tab) if tab else book.sheet1

    def read(self) -> list[list[str]]:
        return self.ws.get_all_values()

    def migrate(self) -> set[str]:
        """Split the old location column in place and strip "Région - " from old Ville cells.
        Returns the columns created empty."""
        from gspread.utils import rowcol_to_a1
        created = set()
        split = location_split(self.ws.row_values(1))
        if split is not None:
            i, before, after = split
            self.ws.update_cell(1, i + 1, "Ville")
            if after:
                self.ws.insert_cols([[h] for h in after], col=i + 2)
            if before:
                self.ws.insert_cols([[h] for h in before], col=i + 1)
            created = set(before + after)
        cells = ville_label_cells(self.read())
        if cells:
            self.ws.batch_update([{"range": rowcol_to_a1(r, c), "values": [[v]]} for (r, c), v in cells.items()],
                                 value_input_option="RAW")
        return created

    def write(self, cells: dict, appended: list) -> None:
        from gspread.utils import rowcol_to_a1
        if cells:
            width = max(c for _, c in cells)
            if width > self.ws.col_count:
                self.ws.add_cols(width - self.ws.col_count)
            self.ws.batch_update([{"range": rowcol_to_a1(r, c), "values": [[v]]} for (r, c), v in cells.items()],
                                 value_input_option="USER_ENTERED")
        if appended:
            self.ws.append_rows(appended, value_input_option="RAW")


# --- entry point ------------------------------------------------------------------------------------------

def tracker_rows(db: str) -> pd.DataFrame:
    """Every person: the contacts and the network members who are not in the contacts."""
    con = duckdb.connect(db, read_only=True)
    try:
        return con.execute("select * exclude (sort_key) from main.tracker_export order by sort_key").df()
    finally:
        con.close()


def sync(client, db: str, outreach_path: str | None = None) -> Plan:
    original = tracker_rows(db)
    current, _ = outreach.overlay(original, outreach.load(outreach_path), notes_column=NOTES_HEADER)
    original[NOTES_HEADER] = ""
    fresh = client.migrate() if hasattr(client, "migrate") else set()    # layout changes first, then read the Sheet
    plan = plan_sync(client.read(), original, current, load_state(outreach_path)["sheet_base"], fresh)
    client.write(plan.cells, plan.appended)               # Sheet first: a failure leaves the state untouched
    apply_plan(plan, current, outreach_path)
    return plan


def main() -> None:
    sheet_id = os.environ.get("CNP_SHEET_ID", "")
    credentials = os.environ.get("CNP_GOOGLE_CREDENTIALS", "data/google-service-account.json")
    if not sheet_id or not Path(credentials).exists():
        print("sheet sync not configured (CNP_SHEET_ID / Google credentials missing): skipped")
        return
    plan = sync(GoogleSheet(sheet_id, credentials, os.environ.get("CNP_SHEET_TAB") or None),
                os.environ.get("CNP_DB", "data/cnp.duckdb"))
    pulled = sum(len(v) for v in plan.local.values())
    pushed = len([1 for (r, _) in plan.cells if r > 1])
    print(f"sheet sync: {pulled} cell(s) from the Sheet, {pushed} to the Sheet, {len(plan.appended)} row(s) added, "
          f"{len(plan.conflicts)} conflict(s) (Sheet kept), {plan.sheet_only} Sheet-only row(s)")
    for name, header, theirs, mine in plan.conflicts:
        print(f"  conflict: {name} / {header}: Sheet '{theirs}' kept, dashboard had '{mine}'")


if __name__ == "__main__":
    main()
