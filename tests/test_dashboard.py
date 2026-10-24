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
    assert metrics["Réseau relié aux contacts"] == "1/12"
    assert metrics["Numéros invalides"] == "2"            # the two short-code entries
    assert metrics["Avec email"] == "1/52"


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
    assert [t.label for t in at.tabs] == ["À faire", "Vue d'ensemble", "Réseau", "Arbre du réseau", "Progression", "Anniversaires", "Prospects", "Suivi"]
