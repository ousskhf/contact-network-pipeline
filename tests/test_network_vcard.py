import pandas as pd

from app.queries import network_export, network_members
from ingest.vcard import card, e164, to_vcard

COLS = ["Nom", "Téléphone", "Téléphone 2", "Téléphone 3", "Autres numéros", "Statut", "Notes"]


def _members(rows):
    return pd.DataFrame(rows, columns=["user_id", "sponsor_id", "name", "grade", "is_active", "person_id",
                                       "link_kind", "phone_norm", "phone2_norm"])


def _wide(rows):
    return pd.DataFrame(rows, columns=COLS)


def test_e164_adds_tunisian_code_and_keeps_foreign_numbers():
    assert e164("20123456") == "+21620123456"
    assert e164("+33612345678") == "+33612345678"
    assert e164("20 123 456") == "+21620123456"


def test_card_has_name_number_and_org_only():
    c = card("Ben Ali, Sami", "20123456", "Acme")
    assert c.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n") and c.endswith("END:VCARD\r\n")
    assert "TEL;TYPE=CELL:+21620123456" in c and "ORG:Acme" in c
    assert "FN:Ben Ali\\, Sami" in c
    assert "NOTE" not in c and "CATEGORIES" not in c
    assert "\n" not in c.replace("\r\n", "")


def test_org_is_left_out_when_not_set_and_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("ORG_NAME", raising=False)
    assert "ORG" not in to_vcard([{"nom": "A B", "téléphone": "20000001"}])
    monkeypatch.setenv("ORG_NAME", "Acme; Co")
    assert "ORG:Acme\\; Co" in to_vcard([{"nom": "A B", "téléphone": "20000001"}])


def test_long_lines_fold_without_splitting_characters():
    c = card("Nom", "20123456", "é" * 120)
    for line in c.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    unfolded = c.replace("\r\n ", "")
    assert "ORG:" + "é" * 120 in unfolded
    unfolded.encode("utf-8").decode("utf-8")


def test_to_vcard_one_card_per_person():
    out = to_vcard([{"nom": "A B", "téléphone": "20000001"}, {"nom": "C D", "téléphone": "20000002"}])
    assert out.count("BEGIN:VCARD") == 2


def test_default_includes_everyone_not_in_contacts_and_status_filters_narrow_it():
    members = _members([
        [1, None, "new blank", "Ambassadeur", True, None, None, "20000001", None],
        [2, 1, "new relancer", "Ambassadeur", True, None, None, "20000002", None],
        [3, 1, "new converti", "Ambassadeur", True, None, None, "20000003", None],
        [4, 1, "in contacts", "Ambassadeur", True, 7, "name_match", "20000004", None],
        [5, 1, "archived", "Ambassadeur", True, None, None, "20000005", None]])
    wide = _wide([
        ["new blank", "20000001", None, None, None, "", "Importé du réseau (membre)"],
        ["new relancer", "20000002", None, None, None, "À relancer", "Importé du réseau (membre)"],
        ["new converti", "20000003", None, None, None, "Converti", "Importé du réseau (membre)"],
        ["archived", "20000005", None, None, None, "Archivé", "Importé du réseau (membre)"]])
    out, skipped = network_export(members, wide)
    assert list(out["nom"]) == ["new blank", "new relancer", "new converti", "archived"] and skipped == 0
    todo, _ = network_export(members, wide, statuses=("À contacter", "À relancer"))
    assert list(todo["nom"]) == ["new blank", "new relancer"]
    assert list(network_export(members, wide, statuses=("Converti",))[0]["nom"]) == ["new converti"]


def test_filters_activity_grade_branch_and_linked_members():
    members = _members([
        [1, None, "top", "Directeur", True, None, None, "20000001", None],
        [2, 1, "child", "Ambassadeur", False, None, None, "20000002", None],
        [3, 2, "grandchild", "Ambassadeur", True, None, None, "20000003", None],
        [4, 1, "linked", "Ambassadeur", True, 9, "name_match", "20000004", None]])
    wide = _wide([["linked", "20000004", None, None, None, "À relancer", None]])
    assert list(network_export(members, wide, active="inactifs")[0]["nom"]) == ["child"]
    assert list(network_export(members, wide, grades=["Directeur"])[0]["nom"]) == ["top"]
    assert list(network_export(members, wide, user_ids={2, 3})[0]["nom"]) == ["child", "grandchild"]
    out = network_export(members, wide, only_new=False, statuses=("À relancer",))[0]
    assert list(out["nom"]) == ["linked"]                      # status found through the contact's number


def test_same_number_link_is_offered_but_a_real_name_match_is_not():
    """A member merely sharing a phone with someone else's contact (link_kind='same_number') is not
    that contact and should still be offered, under their own name; a true name match is not."""
    members = _members([
        [1, None, "shares a number only", "Ambassadeur", True, 5, "same_number", "20000001", None],
        [2, None, "really is a contact", "Ambassadeur", True, 6, "name_match", "20000002", None]])
    out = network_export(members, _wide([]))[0]
    assert list(out["nom"]) == ["shares a number only"]


def test_members_without_a_number_are_counted_not_exported_and_phone2_is_a_fallback():
    members = _members([
        [1, None, "no phone", "Ambassadeur", True, None, None, None, None],
        [2, 1, "second", "Ambassadeur", True, None, None, None, "20000002"]])
    out, skipped = network_export(members, _wide([]))
    assert list(out["nom"]) == ["second"] and out.loc[0, "téléphone"] == "20000002" and skipped == 1


def test_export_on_the_fixtures_warehouse(db, monkeypatch):
    monkeypatch.setenv("CNP_DB", db)
    from app.queries import connect, tracker
    con = connect()
    try:
        members, tr = network_members(con), tracker(con).drop(columns="_network_only")
    finally:
        con.close()
    out, _ = network_export(members, tr.assign(Statut=""), statuses=("À contacter",))
    assert len(out) > 0 and out["téléphone"].str.len().gt(0).all()
    vcf = to_vcard(out.to_dict("records"))
    assert vcf.count("BEGIN:VCARD") == len(out)
