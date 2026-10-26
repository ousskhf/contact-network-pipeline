import pandas as pd
from streamlit.testing.v1 import AppTest

from app import carte


def people(*rows):
    return pd.DataFrame(rows, columns=["Pays", "Région", "Ville"])


def test_region_comes_from_the_region_cell_or_else_the_ville():
    assert carte.region_of("béja ", "") == "Béja"                    # spelling and accents do not matter
    assert carte.region_of("", "Hammamet") == "Nabeul"               # a délégation found in one région only
    assert carte.region_of("", "Sousse") == "Sousse"                 # a ville that is also a région name
    assert carte.region_of("Sahel", "") is None                      # not a governorate
    assert carte.region_of("", "Ariana - Soukra") == "Ariana"        # old "Région - Ville" entry


def test_distribution_counts_people_per_region_and_leaves_abroad_out():
    df = people(("Tunisie", "Tunis", ""), ("", "Tunis", "Bab Souika"), (None, None, "Hammamet"),
                ("France", "Paris", ""), (None, "Sahel", None), (None, None, None))
    regions = carte.by_region(df)
    assert dict(zip(regions["Région"], regions["Personnes"])) == {"Tunis": 2, "Nabeul": 1}
    assert regions["lat"].between(30, 38).all() and regions["lon"].between(7, 12).all()
    assert set(carte.countries(df)["Pays"]) == {"Tunisie", "France"}
    todo = carte.unplaced(df)
    assert dict(zip(todo.index, todo["Raison"])) == {4: "texte non reconnu", 5: "rien de saisi"}


def test_ville_table_lists_placed_people_with_a_ville():
    villes = carte.by_ville(people((None, "Nabeul", "Hammamet"), (None, "Nabeul", "Hammamet"), (None, "Tunis", "")))
    assert villes.to_dict("records") == [{"Région": "Nabeul", "Ville": "Hammamet", "Personnes": 2}]
    assert carte.by_ville(people((None, None, None))).empty


def test_carte_tab_shows_coverage_and_the_people_to_locate(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CNP_DB", db)
    monkeypatch.setenv("CNP_OUTREACH", str(tmp_path / "empty.duckdb"))
    at = AppTest.from_file("../app/dashboard.py", default_timeout=30).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    placed, total = metrics["Sur la carte"].split("/")
    assert 20 <= int(placed) < int(total)                            # the fixtures spread ~20 people over a few régions
    assert metrics["À l'étranger"] == "1"
    assert any(s.value.startswith("À localiser (") for s in at.subheader)
