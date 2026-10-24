import pandas as pd

from ingest import outreach


def tracker():
    return pd.DataFrame({
        "Nom": ["Amal", "Besma", "Chadia"],
        "Téléphone": ["20000001", "20000002", "20000003"],
        "Téléphone 2": ["20000009", None, None], "Téléphone 3": [None, None, None],
        "Autres numéros": [None, None, "20000007 ; 20000008"],
        "Notes": ["Alias(es): A", None, None], "Statut": [None, None, None],
        "Date de Relance": [None, None, None],
    })


def test_save_load_roundtrip_and_replace(tmp_path):
    p = str(tmp_path / "o.duckdb")
    outreach.save({"20000001": {"Statut": "Contacté", "Date de Relance": "2026-10-10", "Notes": ""}}, p)
    got = outreach.load(p).set_index("field")["value"].to_dict()
    assert got == {"Statut": "Contacté", "Date de Relance": "2026-10-10"}      # empty values not stored
    outreach.save({"20000001": {"Statut": ""}}, p)                               # clearing removes the entry
    assert outreach.load(p).empty


def test_overlay_matches_any_number_and_counts_orphans(tmp_path):
    p = str(tmp_path / "o.duckdb")
    outreach.save({"20000009": {"Statut": "Intéressé"},          # second number of Amal
                   "20000008": {"Statut": "Converti"},           # 'Autres numéros' of Chadia
                   "99999999": {"Statut": "À relancer"}}, p)     # nobody has this any more
    df, orphans = outreach.overlay(tracker(), outreach.load(p))
    assert df.loc[0, "Statut"] == "Intéressé" and df.loc[2, "Statut"] == "Converti"
    assert pd.isna(df.loc[1, "Statut"]) and orphans == 1


def test_notes_append_to_import_note_or_go_to_separate_column(tmp_path):
    p = str(tmp_path / "o.duckdb")
    outreach.save({"20000001": {"Notes": "rappeler lundi"}}, p)
    appended, _ = outreach.overlay(tracker(), outreach.load(p))
    assert appended.loc[0, "Notes"] == "Alias(es): A\nrappeler lundi"
    separate, _ = outreach.overlay(tracker(), outreach.load(p), notes_column="Notes perso")
    assert separate.loc[0, "Notes"] == "Alias(es): A" and separate.loc[0, "Notes perso"] == "rappeler lundi"


def test_collect_changes_keeps_hidden_fields():
    shown = pd.DataFrame({"Statut": ["Contacté", None], "Date de Relance": [None, None]}, index=[0, 1])
    edited = shown.copy()
    edited.loc[1, "Statut"] = "Intéressé"                                      # only row 1 edited
    current = pd.DataFrame({f: [""] * 2 for f in outreach.FIELDS}, index=[0, 1])
    current.loc[1, "Genre"] = "F"                                              # stored but not on screen
    phones = pd.Series(["20000001", "20000002"], index=[0, 1])
    changes = outreach.collect_changes(edited, shown, current, phones, ["Statut", "Date de Relance"])
    assert list(changes) == ["20000002"]
    assert changes["20000002"]["Statut"] == "Intéressé" and changes["20000002"]["Genre"] == "F"


def test_members_sharing_a_phone_keep_separate_entries(tmp_path):
    p = str(tmp_path / "o.duckdb")
    note = outreach.NETWORK_NOTE + " (membre)"
    df = pd.DataFrame({"Nom": ["Sponsor", "Recruit", "Friend"], "Téléphone": ["20000005", "20000005", "20000001"],
                       "Téléphone 2": [None] * 3, "Téléphone 3": [None] * 3, "Autres numéros": [None] * 3,
                       "Notes": [note, note, None], "Statut": [None] * 3})
    keys = [outreach.row_key(r) for r in df.to_dict("records")]
    assert keys == ["20000005#sponsor", "20000005#recruit", "20000001"]                # contacts keep the bare phone
    outreach.save({keys[1]: {"Statut": "Contacté"}, keys[2]: {"Statut": "Converti"}}, p)
    out, orphans = outreach.overlay(df, outreach.load(p))
    assert list(out["Statut"].fillna("")) == ["", "Contacté", "Converti"] and orphans == 0


def test_stored_ville_region_moves_to_ville(tmp_path):
    p = str(tmp_path / "o.duckdb")
    con = outreach._connect(p)
    con.execute("delete from migrations")                                      # an install from before the renames
    con.execute("insert into outreach values ('20000001', 'Ville/Région', 'Sfax'), "
                "('20000002', 'Ville/Région', 'Gabès'), ('20000002', 'Localité', 'Gafsa'), "
                "('20000003', 'Localité', 'Sousse')")
    con.close()
    got = outreach.load(p).set_index(["phone", "field"])["value"].to_dict()      # opening the store migrates it
    assert got == {("20000001", "Ville"): "Sfax", ("20000002", "Ville"): "Gafsa", ("20000003", "Ville"): "Sousse"}


def test_a_localite_stored_after_the_migration_is_not_moved_again(tmp_path):
    p = str(tmp_path / "o.duckdb")
    outreach.save({"20000001": {"Ville": "Sfax", "Localité": "Cité Ennasr"}}, p)    # Localité is now the quartier
    outreach.load(p)
    got = outreach.load(p).set_index("field")["value"].to_dict()
    assert got == {"Ville": "Sfax", "Localité": "Cité Ennasr"}


def test_location_overrides_are_kept_by_save(tmp_path):
    p = str(tmp_path / "o.duckdb")
    outreach.save({"20000001": {"Pays": "Tunisie", "Région": "Sahel", "Ville": "Sousse", "Localité": "Cité Khezama",
                                "Adresse": "1 Rue Test"}}, p)
    outreach.save({"20000001": {"Statut": "Contacté"}}, p)                        # a status edit leaves them alone
    got = outreach.load(p).set_index("field")["value"].to_dict()
    assert got == {"Pays": "Tunisie", "Région": "Sahel", "Ville": "Sousse", "Localité": "Cité Khezama",
                   "Adresse": "1 Rue Test", "Statut": "Contacté"}


def test_stored_ville_loses_its_region_prefix_once(tmp_path):
    p = str(tmp_path / "o.duckdb")
    con = outreach._connect(p)
    con.execute("delete from migrations where id like 'ville-without-region%'")
    con.execute("insert into outreach values ('20000001', 'Ville', 'Ariana - Soukra'), ('20000002', 'Ville', 'Monastir'), "
                "('20000003', 'Localité', 'Ariana - Soukra')")                       # only Ville values are touched
    con.close()
    got = outreach.load(p).set_index(["phone", "field"])["value"].to_dict()
    assert got == {("20000001", "Ville"): "Soukra", ("20000002", "Ville"): "Monastir",
                   ("20000003", "Localité"): "Ariana - Soukra"}
    outreach.save({"20000004": {"Ville": "Ariana - Raoued"}}, p)                    # typed later: not rewritten behind its back
    assert outreach.load(p).set_index(["phone", "field"])["value"].to_dict()[("20000004", "Ville")] == "Ariana - Raoued"
