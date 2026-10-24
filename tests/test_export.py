import csv

from ingest.export import export


def _rows(db, tmp_path):
    out = tmp_path / "t.csv"
    n = export(db, str(out))
    return n, list(csv.DictReader(open(out, encoding="utf-8")))


def test_row_count_people_plus_unmatched_network(db, tmp_path):
    n, rows = _rows(db, tmp_path)
    assert n == len(rows) == 41 + 11               # 41 people, 11 of 12 network members not in contacts
    assert "sort_key" not in rows[0]
    assert sum(r["Notes"].startswith("Importé du réseau") for r in rows) == 11


def test_fourth_number_is_not_lost(db, tmp_path):
    _, rows = _rows(db, tmp_path)
    multi = next(r for r in rows if r["Nom"] == "Multi Numbers")
    assert [multi["Téléphone"], multi["Téléphone 2"], multi["Téléphone 3"]] == ["98000001", "70123456", "22000003"]
    assert multi["Autres numéros"] == "70132456"


def test_merged_person_keeps_email_city_profession(db, tmp_path):
    _, rows = _rows(db, tmp_path)
    first = rows[0]
    assert first["Email"] == "amal@example.test"          # same email on two merged rows, listed once
    assert first["Profession"] == "Gérante - Atelier Demo"
    assert first["Région"] == "Sahel" and first["Ville"] == "Sousse"        # each from its own source row


def test_short_codes_kept_but_people_not_merged(db, tmp_path):
    _, rows = _rows(db, tmp_path)
    short = [r for r in rows if r["Nom"].startswith("Short")]
    assert len(short) == 2 and all(r["Téléphone"] == "190" for r in short)


def test_location_columns_replace_ville_region(db, tmp_path):
    _, rows = _rows(db, tmp_path)
    assert "Ville/Région" not in rows[0]
    cols = list(rows[0])
    assert cols[cols.index("Pays"):cols.index("Pays") + 5] == ["Pays", "Région", "Ville", "Localité", "Adresse"]
    assert all(not r["Localité"] for r in rows)                                       # nothing in a phone export is a quartier


def test_town_in_street_field_is_used_as_ville(db, tmp_path):
    _, rows = _rows(db, tmp_path)
    town = next(r for r in rows if r["Nom"].endswith("StreetOnly"))
    assert (town["Ville"], town["Adresse"], town["Région"]) == ("Monastir", "Monastir", "")


def test_country_is_split_from_the_street_text(db, tmp_path):
    _, rows = _rows(db, tmp_path)
    free = next(r for r in rows if r["Nom"].endswith("FreeText"))
    assert (free["Pays"], free["Adresse"], free["Ville"]) == ("Tunisie", "Tunis", "Tunis")
    only = next(r for r in rows if r["Nom"].endswith("CountryOnly"))
    assert (only["Pays"], only["Adresse"], only["Ville"]) == ("Tunisie", "", "")      # a country is not an address
    assert rows[0]["Pays"] == "Tunisie" and rows[0]["Adresse"] == "12 Rue Demo"           # country column, merged rows


def test_network_only_members_have_empty_location(db, tmp_path):
    _, rows = _rows(db, tmp_path)
    net = [r for r in rows if r["Notes"].startswith("Importé du réseau")]
    assert net and all(not r[c] for r in net for c in ("Pays", "Région", "Ville", "Localité", "Adresse"))
