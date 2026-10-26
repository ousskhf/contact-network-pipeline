"""End to end: load fixtures, build dbt marts into a temp DB, render the dashboard."""
from streamlit.testing.v1 import AppTest


def test_dashboard_renders_expected_numbers(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CNP_DB", db)
    monkeypatch.setenv("CNP_OUTREACH", str(tmp_path / "empty.duckdb"))
    at = AppTest.from_file("../app/dashboard.py", default_timeout=30).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Lignes de contacts"] == "44"
    assert metrics["Personnes uniques"] == "41"
    assert metrics["Réseau relié aux contacts"] == "2/12"       # members 0 and 1 share a contact number
    assert metrics["Numéros invalides"] == "2"            # the two short-code entries
    assert metrics["Avec email"] == "1/51"


def test_new_tabs_show_network_health_and_prospects(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CNP_DB", db)
    monkeypatch.setenv("CNP_OUTREACH", str(tmp_path / "empty.duckdb"))
    at = AppTest.from_file("../app/dashboard.py", default_timeout=30).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Membres du réseau"] == "12"
    assert metrics["Inactifs à relancer"] == "3"                  # fixtures: members 0, 4, 8 are blocked
    assert metrics["Prospects (contacts hors réseau)"] == "40"    # 41 people, 1 of them is a network member
    assert metrics["Déjà dans le réseau"] == "1"
    assert [t.label for t in at.tabs] == ["À faire", "Vue d'ensemble", "Réseau", "Arbre du réseau", "Progression",
                                          "Historique", "Anniversaires", "Prospects", "Suivi", "Carte", "Trajets"]


def test_history_tab_renders_with_only_one_day_of_data(db, monkeypatch, tmp_path):
    """The fixtures db has gone through dbt build exactly once: fct_network_history exists (one
    current row per member) but holds no actual transitions yet -- the tab must still render."""
    monkeypatch.setenv("CNP_DB", db)
    monkeypatch.setenv("CNP_OUTREACH", str(tmp_path / "empty.duckdb"))
    at = AppTest.from_file("../app/dashboard.py", default_timeout=30).run()
    assert not at.exception
    hist_tab = next(t for t in at.tabs if t.label == "Historique")
    assert not hist_tab.exception
    assert any("Un seul point pour l'instant" in c.value for c in hist_tab.get("caption"))


def test_overview_lists_shared_numbers_to_check(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CNP_DB", db)
    monkeypatch.setenv("CNP_OUTREACH", str(tmp_path / "empty.duckdb"))
    at = AppTest.from_file("../app/dashboard.py", default_timeout=30).run()
    assert not at.exception
    assert "Numéros partagés : à vérifier" in [s.value for s in at.subheader]
    by_number = next(d for d in at.dataframe if "contact avec ce numéro" in d.value.columns)
    assert len(by_number.value) == 2                      # members 0 and 1 hold a contact's number under other names
    assert set(by_number.value["membres sur ce numéro"]) == {2}


def test_trajets_tab_builds_a_maps_link_for_the_chosen_people(db, monkeypatch, tmp_path):
    import duckdb

    from ingest import outreach
    monkeypatch.setenv("CNP_DB", db)
    monkeypatch.setenv("CNP_OUTREACH", str(tmp_path / "empty.duckdb"))
    con = duckdb.connect(db, read_only=True)
    chosen = con.execute('select "Nom", "Téléphone" from main.tracker_export where "Adresse" like \'12 Rue Demo%\'').fetchall()
    con.close()
    assert len(chosen) == 1
    at = AppTest.from_file("../app/dashboard.py", default_timeout=30).run()
    assert not at.exception
    assert not at.get("link_button")                                   # nobody chosen yet: no link
    at.session_state["route_sel"] = {outreach.row_key({"Nom": nom, "Téléphone": tel}) for nom, tel in chosen}
    at.run()
    assert not at.exception
    (button,) = at.get("link_button")
    url = button.proto.url
    assert url.startswith("https://www.google.com/maps/dir/?api=1") and "travelmode=driving" in url
    assert "12%20Rue%20Demo" in url and "origin=" not in url
