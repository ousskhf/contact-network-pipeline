import duckdb
from streamlit.testing.v1 import AppTest

from app.queries import archived_person_ids, due_followups, invalid_numbers, merge_report, summary, tracker
from ingest import outreach

MULTI = "98000001"            # fixtures: "Multi Numbers", one person with several numbers


def _metrics(db, store, monkeypatch):
    monkeypatch.setenv("CNP_DB", db)
    monkeypatch.setenv("CNP_OUTREACH", store)
    at = AppTest.from_file("../app/dashboard.py", default_timeout=30).run()
    assert not at.exception
    return {m.label: m.value for m in at.metric}, at


def test_archived_contact_leaves_the_dashboard_counts(db, monkeypatch, tmp_path):
    store = str(tmp_path / "o.duckdb")
    before, _ = _metrics(db, store, monkeypatch)
    outreach.save({MULTI: {"Statut": outreach.ARCHIVED}}, store)
    after, at = _metrics(db, store, monkeypatch)
    assert int(after["Personnes uniques"]) == int(before["Personnes uniques"]) - 1
    assert int(after["Numéros"]) < int(before["Numéros"])
    assert int(after["Lignes de contacts"]) < int(before["Lignes de contacts"])
    assert int(after["Prospects (contacts hors réseau)"]) == int(before["Prospects (contacts hors réseau)"]) - 1
    assert int(after["Membres du réseau"]) == int(before["Membres du réseau"])        # members come from the source system
    assert "Archivés" in next(r for r in at.radio if r.label == "Afficher").options    # the way back
    outreach.save({MULTI: {"Statut": ""}}, store)                                      # restoring brings it back
    restored, _ = _metrics(db, store, monkeypatch)
    assert restored == before


def test_queries_leave_out_archived_people_and_closed_follow_ups(db, tmp_path):
    store = str(tmp_path / "o.duckdb")
    outreach.save({MULTI: {"Statut": outreach.ARCHIVED, "Date de Relance": "2020-01-01"}}, store)
    con = duckdb.connect(db, read_only=True)
    wide, _ = outreach.overlay(tracker(con).drop(columns=["_network_only"]), outreach.load(store), notes_column="Notes perso")
    ids = archived_person_ids(con, wide)
    assert len(ids) == 1
    assert summary(con, ids)["people"] == summary(con)["people"] - 1
    assert merge_report(con, ids)["person_id"].isin(ids).sum() == 0
    assert invalid_numbers(con, ids).shape[0] <= invalid_numbers(con).shape[0]
    assert archived_person_ids(con, wide.assign(Statut="")) == []
    from datetime import date
    assert "Multi Numbers" not in set(due_followups(wide, date(2026, 10, 12))["nom"])   # overdue but archived
    con.close()
