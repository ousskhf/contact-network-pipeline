import pandas as pd

from ingest import outreach, sheet_sync
from ingest.sheet_sync import NOTES_HEADER, PIPELINE_COLUMNS, merge_cell, norm, phone_key, plan_sync, sync_key

BASE_COLS = ["Nom", "Téléphone", "Téléphone 2", "Téléphone 3", "Autres numéros", "Notes"]


class FakeSheet:
    """In-memory stand-in for the Google Sheet: a header plus rows of strings."""

    def __init__(self, rows):
        self.rows = [list(r) for r in rows]

    def read(self):
        return [list(r) for r in self.rows]

    def migrate(self):
        split = sheet_sync.location_split(self.rows[0])
        if split is None:
            return set()
        i, before, after = split
        for r, row in enumerate(self.rows):
            if r == 0:
                row[i] = "Ville"
            row[i + 1:i + 1] = after if r == 0 else [""] * len(after)
            row[i:i] = before if r == 0 else [""] * len(before)
        for (r, c), v in sheet_sync.ville_label_cells(self.rows).items():
            self.rows[r - 1][c - 1] = v
        return set(before + after)

    def write(self, cells, appended):
        for (r, c), v in cells.items():
            while len(self.rows) < r:
                self.rows.append([])
            row = self.rows[r - 1]
            row.extend([""] * (c - len(row)))
            row[c - 1] = v
        self.rows.extend(appended)


def tracker_df(people):
    cols = BASE_COLS + sheet_sync.SYNCED + PIPELINE_COLUMNS
    df = pd.DataFrame({c: [p.get(c, "") for p in people] for c in cols})
    return df


def test_phone_key_ignores_zeros_plus_and_spaces():
    assert phone_key("00330600000001") == phone_key("+33 0600000001") == "330600000001"
    assert phone_key(None) == "" and phone_key("20123456") == "20123456"


def test_norm_dates_from_sheet_formats():
    assert norm("Date de Relance", "10/10/2026") == "2026-10-10"
    assert norm("Date de Relance", "2026-10-10") == "2026-10-10"
    assert norm("Statut", "  Contacté ") == "Contacté"


def test_merge_cell_rules():
    assert merge_cell("a", "a", "z") == ("a", "same")
    assert merge_cell("a", "b", "a") == ("b", "local")        # only the dashboard changed
    assert merge_cell("b", "a", "a") == ("b", "sheet")        # only the Sheet changed
    assert merge_cell("c", "b", "a") == ("c", "conflict")     # both changed: the Sheet wins


def test_plan_pulls_pushes_appends_and_reads_custom_columns():
    people = [{"Nom": "Amal", "Téléphone": "20000001"},
              {"Nom": "Besma", "Téléphone": "20000002", "Statut": "Intéressé"},      # set in the dashboard
              {"Nom": "Chadia", "Téléphone": "00330600000001"}]                       # new to the Sheet
    original = tracker_df(people)
    original["Statut"] = ""
    current = tracker_df(people)
    head = BASE_COLS + ["Statut", "Date de Relance", "Couleur"]                       # "Couleur" added by hand
    rows = [head,
            ["Amal", "20000001", "", "", "", "", "Contacté", "10/10/2026", "bleu"],   # edited in the Sheet
            ["Besma", "20000002", "", "", "", "", "", "", ""],
            ["Hors liste", "29999999", "", "", "", "", "", "", ""]]                   # typed in the Sheet
    plan = plan_sync(rows, original, current, {})
    assert plan.local["20000001"] == {"Statut": "Contacté", "Date de Relance": "2026-10-10"}
    assert plan.cells[(3, head.index("Statut") + 1)] == "Intéressé"                   # dashboard value pushed
    assert (1, len(head) + 1) in plan.cells                                           # missing headers are added
    assert len(plan.appended) == 1 and plan.appended[0][1] == "00330600000001"
    assert plan.extra[("20000001", "Couleur")] == "bleu"
    assert plan.sheet_only == 1 and not plan.conflicts


def test_plan_conflict_keeps_sheet_value_and_second_sync_is_quiet():
    people = [{"Nom": "Amal", "Téléphone": "20000001", "Statut": "Converti"}]
    original = tracker_df([{"Nom": "Amal", "Téléphone": "20000001"}])
    current = tracker_df(people)
    head = BASE_COLS + sheet_sync.SYNCED + PIPELINE_COLUMNS
    row = ["Amal", "20000001"] + [""] * (len(head) - 2)
    row[head.index("Statut")] = "Contacté"
    plan = plan_sync([head, row], original, current, {})
    assert plan.conflicts == [("Amal", "Statut", "Contacté", "Converti")]
    assert plan.local["20000001"]["Statut"] == "Contacté" and not plan.cells
    again = plan_sync([head, row], original, tracker_df([{"Nom": "Amal", "Téléphone": "20000001",
                                                             "Statut": "Contacté"}]), plan.base)
    assert not again.local and not again.cells and not again.conflicts


def test_end_to_end_with_pipeline_data(db, tmp_path):
    store = str(tmp_path / "o.duckdb")
    base = sheet_sync.tracker_rows(db)
    assert base["Notes"].fillna("").str.startswith(outreach.NETWORK_NOTE).any()          # network-only members are included
    head = BASE_COLS + sheet_sync.SYNCED + PIPELINE_COLUMNS
    sheet = FakeSheet([head] + [[sheet_sync.norm(h, r.get(h) if h != NOTES_HEADER else "") for h in head]
                                for r in base.to_dict("records")])
    first = sheet_sync.sync(sheet, db, store)
    assert not first.local and not first.cells and not first.appended and not first.conflicts
    # edits in the Sheet on the first person; a dashboard entry on the second
    at = {h: head.index(h) for h in ("Statut", "Date de Relance", "Email")}
    sheet.rows[1][at["Statut"]], sheet.rows[1][at["Date de Relance"]] = "Intéressé", "10/11/2026"
    sheet.rows[1][at["Email"]] = "amal@example.com"
    outreach.save({base.iloc[1]["Téléphone"]: {"Statut": "Contacté"}}, store)
    second = sheet_sync.sync(sheet, db, store)
    stored = outreach.load(store).groupby("phone")["value"].apply(set).to_dict()
    assert {"Intéressé", "2026-11-10", "amal@example.com"} <= stored[base.iloc[0]["Téléphone"]]
    assert sheet.rows[2][at["Statut"]] == "Contacté"                              # pushed to the Sheet
    assert not second.conflicts
    third = sheet_sync.sync(sheet, db, store)                                     # stable once converged
    assert not third.local and not third.cells and not third.conflicts


def test_members_sharing_a_phone_are_separate_rows_and_network_data_is_pushed():
    people = [{"Nom": "Sponsor", "Téléphone": "20000005", "Notes": outreach.NETWORK_NOTE + " (membre)",
               "Grade": "Gold", "Actif": "Oui"},
              {"Nom": "Recruit", "Téléphone": "20000005", "Notes": outreach.NETWORK_NOTE + " (membre)",
               "Grade": "Silver", "Actif": "Non"},
              {"Nom": "Friend", "Téléphone": "20000001", "Grade": "Platinum", "Actif": "Oui"}]
    assert sync_key("20000005", "Sponsor", people[0]["Notes"]) != sync_key("20000005", "Recruit", people[1]["Notes"])
    assert sync_key("0020000001", "Friend", "") == "20000001"                          # contacts: phone only
    original, current = tracker_df(people), tracker_df(people)
    head = BASE_COLS + sheet_sync.SYNCED + PIPELINE_COLUMNS
    blank = [""] * (len(head) - 2)
    rows = [head, ["Sponsor", "20000005"] + blank, ["Friend", "20000001"] + blank]   # the Sheet has two of the three
    rows[1][head.index("Notes")] = people[0]["Notes"]
    plan = plan_sync(rows, original, current, {})
    assert [r[0] for r in plan.appended] == ["Recruit"]                                # same phone, still its own row
    assert plan.cells[(2, head.index("Grade") + 1)] == "Gold"                   # network data overwrites the Sheet
    assert plan.cells[(3, head.index("Actif") + 1)] == "Oui"


def test_location_split_keeps_the_old_column_as_ville():
    head = ["Nom", "Téléphone", "Ville/Région", "Email"]
    assert sheet_sync.location_split(head) == (2, ["Pays", "Région"], ["Localité", "Adresse"])
    # a Sheet already split in four: its Localité held the town, it becomes Ville and a new Localité follows
    assert sheet_sync.location_split(["Nom", "Pays", "Région", "Localité", "Adresse"]) == (3, [], ["Localité"])
    assert sheet_sync.location_split(["Nom", "Pays", "Région", "Ville", "Localité", "Adresse"]) is None
    assert sheet_sync.location_split(["Nom", "Téléphone", "Email"]) is None


def test_new_columns_are_filled_not_read_as_a_deletion():
    people = [{"Nom": "Amal", "Téléphone": "20000001", "Pays": "Tunisie", "Région": "Sahel"}]
    original = current = tracker_df(people)
    head = BASE_COLS + sheet_sync.SYNCED + PIPELINE_COLUMNS
    row = ["Amal", "20000001"] + [""] * (len(head) - 2)                              # blank Pays/Région in the Sheet
    plan = plan_sync([head, row], original, current, {}, fresh={"Pays", "Région"})
    assert plan.cells[(2, head.index("Pays") + 1)] == "Tunisie" and plan.cells[(2, head.index("Région") + 1)] == "Sahel"
    assert not plan.local
    kept = plan_sync([head, row], original, current, {})                             # a synced column: blank = cleared
    assert kept.local["20000001"]["Pays"] == "" and not kept.cells


LOCATION = ["Pays", "Région", "Ville", "Localité", "Adresse"]


def _old_sheet(base, legacy):
    """The Sheet as it was: one Ville/Région column (legacy="one") or four columns with the town in Localité."""
    keep = [h for h in BASE_COLS + sheet_sync.SYNCED + PIPELINE_COLUMNS if h not in LOCATION]
    at = keep.index("Email") + 1
    block = ["Ville/Région"] if legacy == "one" else ["Pays", "Région", "Localité", "Adresse"]
    head = keep[:at] + block + keep[at:]
    value = lambda r, h: (r.get("Ville") if h in ("Ville/Région", "Localité") else "" if h == NOTES_HEADER else r.get(h))
    rows = [[sheet_sync.norm(h, value(r, h)) for h in head] for r in base.to_dict("records")]
    return FakeSheet([head] + rows), head


def test_migration_splits_the_sheet_and_follows_the_stored_values(db, tmp_path):
    for legacy in ("one", "four"):
        store = str(tmp_path / f"{legacy}.duckdb")
        base = sheet_sync.tracker_rows(db)
        sheet, old_head = _old_sheet(base, legacy)
        first_person = base.iloc[0]
        town = "Ville/Région" if legacy == "one" else "Localité"
        sheet.rows[1][old_head.index(town)] = "Sfax"                              # town corrected in the Sheet
        if legacy == "four":                                                       # the nightly sync had written these
            for r, row in zip(base.to_dict("records"), sheet.rows[1:]):
                row[old_head.index("Pays")], row[old_head.index("Région")] = r["Pays"] or "", r["Région"] or ""
        plan = sheet_sync.sync(sheet, db, store)
        head = sheet.rows[0]
        at = head.index
        assert head[at("Pays"):at("Pays") + 5] == LOCATION and "Ville/Région" not in head
        assert sheet.rows[1][at("Ville")] == "Sfax"                                # the user's town is kept
        assert sheet.rows[1][at("Pays")] == first_person["Pays"]                   # new columns are filled in
        assert sheet.rows[1][at("Région")] == first_person["Région"]
        assert sheet.rows[1][at("Localité")] == ""                                 # nothing known about the quartier
        stored = outreach.load(store)
        assert stored[(stored["phone"] == first_person["Téléphone"]) & (stored["field"] == "Ville")]["value"].tolist() == ["Sfax"]
        assert not plan.conflicts
        again = sheet_sync.sync(sheet, db, store)
        assert not again.local and not again.cells and not again.conflicts


def test_old_ville_entries_read_as_the_plain_name():
    assert norm("Ville", "Ariana - Soukra") == norm("Ville", "Soukra") == "Soukra"
    assert norm("Ville", "Ariana - Nulle part") == "Ariana - Nulle part" and norm("Localité", "Ariana - Soukra") == "Ariana - Soukra"
    rows = [["Nom", "Téléphone", "Ville"], ["A", "20000001", "Ariana - Soukra"], ["B", "20000002", "Soukra"],
            ["C", "20000003", ""], ["D", "20000004", "Le Kef - Dahmani"], ["E"]]
    assert sheet_sync.ville_label_cells(rows) == {(2, 3): "Soukra", (5, 3): "Dahmani"}
    assert sheet_sync.ville_label_cells([["Nom", "Téléphone"]]) == {}


def test_a_sheet_that_still_holds_the_old_entry_does_not_pull_it_back():
    people = [{"Nom": "Amal", "Téléphone": "20000001", "Ville": "Soukra"}]            # stored without the prefix
    original = current = tracker_df(people)
    head = BASE_COLS + sheet_sync.SYNCED + PIPELINE_COLUMNS
    row = ["Amal", "20000001"] + [""] * (len(head) - 2)
    row[head.index("Ville")] = "Ariana - Soukra"
    plan = plan_sync([head, row], original, current, {("20000001", "Ville"): "Soukra"})
    assert not plan.local and not plan.conflicts and (2, head.index("Ville") + 1) not in plan.cells
