from ingest import locations, outreach, sheet_format
from ingest.sheet_format import build_requests, cleanup_requests, col_letter

HEADER = ["Nom", "Téléphone", "Statut", "Date de Relance", "Genre", "Notes", "Notes perso", "Couleur"]


def kinds(reqs):
    return [next(iter(r)) for r in reqs]


def test_dropdowns_dates_and_status_colours_follow_the_headers():
    reqs = build_requests(7, HEADER)
    lists = {r["setDataValidation"]["range"]["startColumnIndex"]: r["setDataValidation"]["rule"]
             for r in reqs if "rule" in r.get("setDataValidation", {})
             and r["setDataValidation"]["rule"]["condition"]["type"] == "ONE_OF_LIST"}
    statut = [v["userEnteredValue"] for v in lists[HEADER.index("Statut")]["condition"]["values"]]
    assert statut == outreach.STATUTS and lists[HEADER.index("Genre")]["strict"] is False   # other values still allowed
    assert any(r["setDataValidation"]["rule"]["condition"]["type"] == "DATE_IS_VALID"
               for r in reqs if "rule" in r.get("setDataValidation", {}))
    assert kinds(reqs).count("addConditionalFormatRule") == len(sheet_format.STATUS_COLORS) + 2   # statuses + overdue date + archived row
    formulas = [r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
                for r in reqs if "addConditionalFormatRule" in r
                and r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["type"] == "CUSTOM_FORMULA"]
    assert "=AND(ISNUMBER(D2),D2<TODAY())" in formulas                                       # column D = Date de Relance
    assert '=$C2="Archivé"' in formulas                                                       # column C = Statut


def test_pipeline_columns_are_greyed_and_warn_only_and_custom_columns_untouched():
    reqs = build_requests(7, HEADER)
    protected = {r["addProtectedRange"]["protectedRange"]["range"]["startColumnIndex"] for r in reqs if "addProtectedRange" in r}
    assert protected == {HEADER.index(h) for h in ("Nom", "Téléphone", "Notes")}
    assert all(r["addProtectedRange"]["protectedRange"]["warningOnly"] for r in reqs if "addProtectedRange" in r)
    touched = {r[k]["range"].get("startColumnIndex") for r in reqs for k in r if isinstance(r[k], dict) and "range" in r[k]}
    assert HEADER.index("Couleur") not in touched                                            # added by hand: left alone


def test_missing_headers_are_skipped_and_cleanup_removes_old_rules():
    reqs = build_requests(7, ["Nom", "Téléphone"])
    assert "addConditionalFormatRule" not in kinds(reqs) and "setDataValidation" not in kinds(reqs)
    meta = {"properties": {"sheetId": 7}, "conditionalFormats": [{}, {}],
            "protectedRanges": [{"protectedRangeId": 5, "description": sheet_format.PROTECT_NOTE},
                                {"protectedRangeId": 6, "description": "someone else's"}]}
    assert kinds(cleanup_requests(meta)) == ["deleteConditionalFormatRule"] * 2 + ["deleteProtectedRange"]


def test_col_letter():
    assert [col_letter(i) for i in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]


def _validations(reqs):
    return {r["setDataValidation"]["range"]["startColumnIndex"]: r["setDataValidation"].get("rule")
            for r in reqs if "setDataValidation" in r}


def test_country_and_region_accept_only_their_list():
    header = ["Nom", "Pays", "Région", "Ville", "Localité", "Adresse", "Genre"]
    rules = _validations(build_requests(7, header))
    values = lambda i: [v["userEnteredValue"] for v in rules[i]["condition"]["values"]]
    assert values(1) == ["Tunisie"] and rules[1]["strict"] is True                 # Pays: Tunisia only
    assert len(values(2)) == 24 and "Sousse" in values(2) and rules[2]["strict"] is True
    assert rules[5] is None                                                          # Adresse: free text, inherited list cleared


def test_ville_and_localite_are_left_to_the_script_and_adresse_is_free_text():
    header = ["Nom", "Pays", "Région", "Ville", "Localité", "Adresse"]
    rules = _validations(build_requests(7, header))
    assert 3 not in rules and 4 not in rules          # the script sets a rule per row; a column rule would erase them
    assert rules[5] is None                           # Adresse: free text, a list inherited from its neighbour is cleared
    first_run = _validations(build_requests(7, header, clear_ville=True))
    assert first_run[3] is None and 4 not in first_run   # once, to drop the old flat Ville list; never Localité


def test_lieux_tab_has_region_ville_localite_for_every_localite():
    rows = sheet_format.lieux_matrix()
    assert rows[0] == ["Région", "Ville", "Localité"] and len(rows) == len(locations.lieux_rows()) + 1
    assert ["Ariana", "Soukra", "Cité Ghouzaila"] in rows and all(len(r) == 3 for r in rows)
    assert not any(r[1].startswith(r[0] + " - ") for r in rows[1:])        # plain ville names, no "Région - " in front


def test_apps_script_reads_the_tabs_and_headers_the_sheet_writes():
    from pathlib import Path
    script = (Path(__file__).parent.parent / "apps_script" / "Localites.gs").read_text(encoding="utf-8")
    assert f"var LIEUX_TAB = '{sheet_format.LIEUX_TAB}'" in script and f"var DATA_TAB = '{sheet_format.DATA_TAB}'" in script
    for header in ("Région", "Ville", "Localité"):
        assert f"col['{header}']" in script
    assert "setAllowInvalid(true)" in script and "getRange(2, 1, tab.getLastRow() - 1, 3)" in script
    assert "function installTrigger()" in script and "newTrigger('refreshAll').timeBased().everyDays(1)" in script
