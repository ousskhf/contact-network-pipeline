import pandas as pd

from ingest import outreach


def _tracker(rows):
    cols = ["Nom", "Téléphone", "Téléphone 2", "Téléphone 3", "Autres numéros", "Notes"]
    return pd.DataFrame(rows, columns=cols)


def _stored(path):
    return {(p, f): v for p, f, v in outreach._connect(path).execute("select * from outreach").fetchall()}


def test_member_who_became_a_contact_keeps_status_and_old_rows_are_removed(tmp_path):
    path = str(tmp_path / "o.duckdb")
    outreach.save({"20000001#amira": {"Statut": "Converti", "Notes": "vu"}}, path)
    tracker = _tracker([["Amira", "20000001", None, None, None, None]])
    assert outreach.rekey_linked_members(tracker, path)["moved"] == 1       # dry run: reports only
    assert ("20000001#amira", "Statut") in _stored(path)
    outreach.rekey_linked_members(tracker, path, apply=True)
    assert _stored(path) == {("20000001", "Statut"): "Converti", ("20000001", "Notes"): "vu"}


def test_member_still_network_only_is_left_alone(tmp_path):
    path = str(tmp_path / "o.duckdb")
    outreach.save({"20000001#amira": {"Statut": "Converti"}}, path)
    tracker = _tracker([["Amira", "20000001", None, None, None, "Importé du réseau (membre)"]])
    stats = outreach.rekey_linked_members(tracker, path, apply=True)
    assert stats["still_network"] == 1 and ("20000001#amira", "Statut") in _stored(path)


def test_conflicts_and_ambiguous_matches_are_never_changed(tmp_path):
    path = str(tmp_path / "o.duckdb")
    outreach.save({"20000001#amira": {"Statut": "Converti"}, "20000001": {"Statut": "Contacté"},
                   "20000002#sami": {"Statut": "Converti"}}, path)
    tracker = _tracker([["Amira", "20000001", None, None, None, None],
                        ["Parent", "20000002", None, None, None, None],
                        ["Other", "20000002", None, None, None, None]])
    before = _stored(path)
    stats = outreach.rekey_linked_members(tracker, path, apply=True)
    assert stats["conflicts"] == 1 and stats["ambiguous"] == 1 and stats["moved"] == 0
    assert _stored(path) == before


def test_shared_phone_is_disambiguated_by_name(tmp_path):
    path = str(tmp_path / "o.duckdb")
    outreach.save({"20000002#sami": {"Statut": "Converti"}}, path)
    tracker = _tracker([["Parent", "20000002", None, None, None, None], ["Sami", "20000009", "20000002", None, None, None]])
    outreach.rekey_linked_members(tracker, path, apply=True)
    assert _stored(path) == {("20000009", "Statut"): "Converti"}
