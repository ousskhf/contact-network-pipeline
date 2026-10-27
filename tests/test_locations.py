import pandas as pd

from ingest import locations, sheet_format


def test_every_governorate_is_there_with_villes_and_localites():
    tree = locations.load()
    assert len(tree) == 24 and tree["Ariana"] and tree["La Manouba"] and tree["Médenine"]
    assert sheet_format.DROPDOWNS["Région"] == list(tree)
    for region, villes in tree.items():
        assert villes, region
        for ville, items in villes.items():
            assert items, (region, ville)
            assert len({i.lower() for i in items}) == len(items), (region, ville)       # no duplicate in a list


def test_the_hierarchy_matches_the_postal_data():
    assert {"Ariana Ville", "Soukra", "Raoued"} <= set(locations.villes("Ariana"))
    assert {"Cité Ghouzaila", "Cité Hedi Nouira", "Cité Snit", "Cité Star", "Résidence El Ouns"} <= set(
        locations.localites("Ariana", "Soukra"))
    assert locations.localites("Ariana", "Nulle part") == [] and locations.villes("Nulle part") == []
    assert locations.COUNTRY == "Tunisie"


def test_names_are_clean():
    for villes in locations.load().values():
        for ville, items in villes.items():
            assert ville == " ".join(ville.split()) and all(i and i == " ".join(i.split()) for i in items)


def test_lieux_rows_give_region_ville_and_localite_for_every_localite():
    rows = locations.lieux_rows()
    assert len(rows) == sum(len(i) for v in locations.load().values() for i in v.values())
    assert ("Ariana", "Soukra", "Cité Ghouzaila") in rows and all(len(r) == 3 for r in rows)


def test_strip_region_removes_the_old_prefix_of_known_villes_only():
    assert locations.strip_region("Ariana - Soukra") == "Soukra"
    assert locations.strip_region("Le Kef - Dahmani") == "Dahmani"
    assert locations.strip_region("Soukra") == "Soukra" and locations.strip_region("") == ""
    assert locations.strip_region("Ariana - Nulle part") == "Ariana - Nulle part"      # unknown: left as typed
    assert locations.strip_region(None) == ""
    assert locations.strip_region(float("nan")) == "" and locations.strip_region(pd.NA) == ""     # a missing cell, not "nan"
