"""Make the shared Sheet easier to edit: dropdowns, date pickers, colours, frozen header, filter, widths.

Safe to run again: it only sets formatting and rules, never cell values (except the help tab). Columns are
found by their header, so reordering or adding columns is fine. Dropdowns accept other values too (a warning,
not a refusal), because the dashboard and the sync can store free text. Existing conditional-format rules on
the data tab are replaced, so put your own rules on another tab.

    make format-sheet        # needs the same CNP_SHEET_ID and Google key as make sync
"""
import os
from pathlib import Path

from ingest import locations, outreach
from ingest.sheet_sync import NOTES_HEADER, READ_ONLY

ROWS = 2000                                    # rules cover this many rows, so appended rows inherit them
HELP_TAB = "Mode d'emploi"
DATA_TAB = "Contacts"
PROTECT_NOTE = "Géré par le pipeline (lecture seule)"

STRICT = {"Pays", "Région"}                   # only the listed values; the other lists warn but accept other values
# Région, Ville and Localité form a chain: the Ville list of a row depends on its Région and the Localité list on its
# Ville, which the Sheets API cannot do (it ignores INDIRECT in validation rules, and one rule plus one helper formula per
# row makes the Sheet unusably slow). apps_script/Localites.gs, pasted once into the Sheet, sets the per-row lists from the
# hidden Lieux tab (région, ville, localité), so this module only writes that tab and leaves Ville and Localité alone.
LIEUX_TAB = "Lieux"
OLD_TABS = ("Listes villes", "Listes localités", "Aide villes", "Aide localités")      # earlier attempts, removed
LEGACY_LISTS_TAB = "Listes"                    # the flat "Région - Ville" list, replaced by the script

DROPDOWNS = {
    "Pays": [locations.COUNTRY],
    "Région": locations.regions(),
    "Statut": outreach.STATUTS,
    "Type d'Intérêt": ["Client", "Bronze", "Les deux"],
    "Genre": ["Femme", "Homme"],
    "Langue Préférée": ["Arabe", "Français", "Anglais"],
    "Tranche d'Âge": ["18-25", "26-35", "36-45", "46-55", "56 et plus"],
}
STATUS_COLORS = {                              # background, text
    "À contacter": ((0.93, 0.93, 0.93), (0.25, 0.25, 0.25)),
    "Contacté": ((0.85, 0.92, 0.98), (0.10, 0.25, 0.45)),
    "Intéressé": ((0.85, 0.95, 0.88), (0.10, 0.35, 0.18)),
    "À relancer": ((1.00, 0.92, 0.80), (0.55, 0.30, 0.00)),
    "Converti": ((0.72, 0.88, 0.76), (0.05, 0.28, 0.12)),
    "Pas intéressé": ((0.90, 0.90, 0.90), (0.45, 0.45, 0.45)),
    outreach.ARCHIVED: ((0.96, 0.96, 0.96), (0.55, 0.55, 0.55)),
}
WIDTHS = {"Nom": 220, "Téléphone": 115, "Téléphone 2": 115, "Téléphone 3": 115, "Autres numéros": 150,
          "Notes": 240, NOTES_HEADER: 260, "Email": 210, "Pays": 110, "Région": 130, "Ville": 160, "Localité": 190, "Adresse": 220,
          "Profession": 160}
HEADER_BG, READ_ONLY_BG = (0.13, 0.27, 0.42), (0.94, 0.94, 0.94)

HELP_TEXT = [
    ["Mode d'emploi"],
    [""],
    ["Cette feuille est partagée et synchronisée avec le tableau de bord."],
    [""],
    ["Colonnes grises : nom, numéros, notes d'import, grade et actif. Elles sont gérées automatiquement, ne pas les modifier."],
    ["Les lignes dont la note d'import indique « Importé du réseau » sont des membres du réseau qui ne sont pas dans les contacts du téléphone."],
    ["Colonnes blanches : à remplir. Plusieurs ont une liste déroulante ; une autre valeur peut aussi être tapée."],
    ["Statut : la cellule prend une couleur selon le statut."],
    ["Statut Archivé : le contact reste dans cette feuille (ligne grisée) mais est ignoré partout dans l'application. Pour le restaurer, changer son statut."],
    ["Pays, Région, Localité, Adresse : le lieu, du plus large au plus précis. Pays et Région (gouvernorat) n'acceptent que la liste. Ville et Localité sont liées : la liste de la Ville dépend de la Région choisie, et celle de la Localité (cité, quartier) dépend de la Ville (si le script des lieux est installé) ; une autre valeur peut être tapée. Choisir d'abord la Région, puis la Ville, puis la Localité. Adresse est libre."],
    ["Date de Relance : elle passe en rouge quand la date est dépassée."],
    ["Notes perso : pour les remarques personnelles. Les colonnes Notes (grise) sont gérées par le pipeline."],
    [""],
    ["Ajouter une colonne : écrire un titre dans la première cellule libre à droite des titres existants. Elle est conservée."],
    ["Ne pas renommer ni supprimer les titres existants, et ne pas supprimer de lignes."],
    [""],
    ["Synchronisation : une fois par jour, la nuit, les modifications de la feuille et du tableau de bord sont fusionnées."],
    ["Si la même cellule est modifiée des deux côtés avant la synchronisation, la version de cette feuille est gardée."],
]


def rgb(c):
    return {"red": c[0], "green": c[1], "blue": c[2]}


def col_letter(index: int) -> str:
    s, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def build_requests(sheet_id: int, header: list[str], rows: int = ROWS, clear_ville: bool = False) -> list[dict]:
    col = {h: i for i, h in enumerate(header)}
    full = lambda h: {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": rows,
                      "startColumnIndex": col[h], "endColumnIndex": col[h] + 1}
    reqs = [
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties":
                                                  {"frozenRowCount": 1, "frozenColumnCount": 1}},
                                   "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                                  "startColumnIndex": 0, "endColumnIndex": len(header)},
                        "cell": {"userEnteredFormat": {"backgroundColor": rgb(HEADER_BG), "verticalAlignment": "MIDDLE",
                                                       "wrapStrategy": "WRAP",
                                                       "textFormat": {"bold": True, "foregroundColor": rgb((1, 1, 1))}}},
                        "fields": "userEnteredFormat.backgroundColor,userEnteredFormat.verticalAlignment,"
                                  "userEnteredFormat.wrapStrategy,userEnteredFormat.textFormat"}},
        {"setBasicFilter": {"filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": rows,
                                                 "startColumnIndex": 0, "endColumnIndex": len(header)}}}},
    ]
    for h in header:
        if h in READ_ONLY:
            reqs.append({"repeatCell": {"range": full(h), "cell": {"userEnteredFormat": {"backgroundColor": rgb(READ_ONLY_BG)}},
                                        "fields": "userEnteredFormat.backgroundColor"}})
            reqs.append({"addProtectedRange": {"protectedRange": {"range": full(h), "description": PROTECT_NOTE,
                                                                  "warningOnly": True}}})
        if h in ("Notes", NOTES_HEADER):
            reqs.append({"repeatCell": {"range": full(h), "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                                        "fields": "userEnteredFormat.wrapStrategy"}})
        if h in WIDTHS:
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col[h], "endIndex": col[h] + 1},
                "properties": {"pixelSize": WIDTHS[h]}, "fields": "pixelSize"}})
    for h in outreach.LOCATION_FIELDS:             # free text: a column inserted next to a dropdown inherits its list
        if h in col and (h == "Adresse" or (h == "Ville" and clear_ville)):
            reqs.append({"setDataValidation": {"range": full(h)}})
    for h, options in DROPDOWNS.items():
        if h in col:
            reqs.append({"setDataValidation": {"range": full(h), "rule": {
                "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in options]},
                "showCustomUi": True, "strict": h in STRICT}}})
    for h in outreach.DATE_FIELDS:
        if h in col:
            reqs.append({"setDataValidation": {"range": full(h), "rule": {
                "condition": {"type": "DATE_IS_VALID"}, "showCustomUi": True, "strict": False}}})
            reqs.append({"repeatCell": {"range": full(h), "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}}, "fields": "userEnteredFormat.numberFormat"}})
    if "Statut" in col:
        letter = col_letter(col["Statut"])                       # archived rows: whole row in grey italics
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": rows,
                        "startColumnIndex": 0, "endColumnIndex": len(header)}],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                          "values": [{"userEnteredValue": f'=${letter}2="{outreach.ARCHIVED}"'}]},
                            "format": {"textFormat": {"foregroundColor": rgb((0.60, 0.60, 0.60)), "italic": True}}}}}})
        for status, (bg, fg) in STATUS_COLORS.items():
            reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [full("Statut")],
                "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": status}]},
                                "format": {"backgroundColor": rgb(bg), "textFormat": {"foregroundColor": rgb(fg)}}}}}})
    if "Date de Relance" in col:
        letter = col_letter(col["Date de Relance"])
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [full("Date de Relance")],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                          "values": [{"userEnteredValue": f'=AND(ISNUMBER({letter}2),{letter}2<TODAY())'}]},
                            "format": {"backgroundColor": rgb((0.98, 0.82, 0.80)),
                                       "textFormat": {"foregroundColor": rgb((0.65, 0.10, 0.08)), "bold": True}}}}}})
    return reqs


def cleanup_requests(sheet_meta: dict) -> list[dict]:
    """Remove what a previous run added, so running again does not stack duplicates."""
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sheet_meta["properties"]["sheetId"], "index": 0}}
            for _ in sheet_meta.get("conditionalFormats", [])]
    reqs += [{"deleteProtectedRange": {"protectedRangeId": p["protectedRangeId"]}}
             for p in sheet_meta.get("protectedRanges", []) if p.get("description") == PROTECT_NOTE]
    return reqs


def lieux_matrix() -> list[list[str]]:
    """Content of the Lieux tab: header, then one (région, ville, localité) row per localité."""
    return [["Région", "Ville", "Localité"]] + [list(row) for row in locations.lieux_rows()]


def write_list_tab(book) -> bool:
    """(Re)write the hidden Lieux tab and drop the tabs of earlier attempts. True when the old flat Ville list existed,
    so the Ville column still carries its validation rule and must be cleared once."""
    legacy = False
    for title in (*OLD_TABS, LEGACY_LISTS_TAB):
        try:
            book.del_worksheet(book.worksheet(title))
            legacy = legacy or title == LEGACY_LISTS_TAB
        except Exception:
            pass
    matrix = lieux_matrix()
    try:
        tab = book.worksheet(LIEUX_TAB)
        tab.clear()
        tab.resize(rows=len(matrix), cols=len(matrix[0]))
    except Exception:
        tab = book.add_worksheet(LIEUX_TAB, rows=len(matrix), cols=len(matrix[0]))
    tab.update(range_name="A1", values=matrix)
    tab.freeze(rows=1)
    tab.hide()
    return legacy


def apply(book, ws) -> int:
    meta = next(s for s in book.fetch_sheet_metadata()["sheets"] if s["properties"]["sheetId"] == ws.id)
    header = ws.row_values(1)
    if ws.title != DATA_TAB:
        ws.update_title(DATA_TAB)
    legacy = write_list_tab(book)
    reqs = cleanup_requests(meta) + build_requests(ws.id, header, clear_ville=legacy)
    book.batch_update({"requests": reqs})
    try:
        help_ws = book.worksheet(HELP_TAB)
    except Exception:
        help_ws = book.add_worksheet(HELP_TAB, rows=30, cols=2)
    help_ws.update(range_name="A1", values=HELP_TEXT)
    help_ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    book.batch_update({"requests": [{"updateDimensionProperties": {
        "range": {"sheetId": help_ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 900}, "fields": "pixelSize"}}]})
    return len(reqs)


def main() -> None:
    import gspread
    sheet_id = os.environ.get("CNP_SHEET_ID", "")
    credentials = os.environ.get("CNP_GOOGLE_CREDENTIALS", "data/google-service-account.json")
    if not sheet_id or not Path(credentials).exists():
        print("sheet not configured (CNP_SHEET_ID / Google credentials missing): skipped")
        return
    book = gspread.service_account(filename=credentials).open_by_key(sheet_id)
    print(f"sheet formatting: {apply(book, book.sheet1)} request(s) applied")


if __name__ == "__main__":
    main()
