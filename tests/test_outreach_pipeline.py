import csv

from ingest import outreach
from ingest.export import export


def test_export_carries_saved_outreach_and_survives_reexport(db, tmp_path):
    store = str(tmp_path / "o.duckdb")
    outreach.save({"98000001": {"Statut": "Contacté", "Date de Relance": "2026-10-10", "Notes": "rappeler lundi"}}, store)
    out = tmp_path / "t.csv"
    export(db, str(out), store)
    export(db, str(out), store)                                   # idempotent
    row = next(r for r in csv.DictReader(open(out, encoding="utf-8")) if r["Nom"] == "Multi Numbers")
    assert (row["Statut"], row["Date de Relance"]) == ("Contacté", "2026-10-10")
    assert row["Notes"] == "rappeler lundi"                      # nothing else in Notes for this person
