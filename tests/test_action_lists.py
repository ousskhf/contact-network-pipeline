from datetime import date

import pandas as pd

from app.queries import (due_followups, inactive_by_impact, near_promotion, unscheduled_interested,
                         whatsapp_link)

TODAY = date(2026, 10, 12)


def _wide(rows):
    cols = ["Nom", "Téléphone", "Statut", "Date de Relance", "Date de Dernier Contact", "Produit d'Intérêt"]
    return pd.DataFrame(rows, columns=cols)


def test_due_followups_overdue_first_and_closed_excluded():
    wide = _wide([
        ["late", "20000001", "Contacté", "2026-10-02", "2026-09-30", ""],
        ["today", "20000002", "Intéressé", "2026-10-12", "", "parfum"],
        ["future", "20000003", "Contacté", "2026-10-20", "", ""],
        ["flagged", "20000004", "À relancer", "", "", ""],
        ["done", "20000005", "Converti", "2026-10-01", "", ""],
        ["no", "20000006", "Pas intéressé", "2026-10-01", "", ""],
        ["new", "20000007", "", "", "", ""]])
    out = due_followups(wide, TODAY)
    assert list(out["nom"]) == ["late", "today", "flagged"]
    assert list(out["en retard (jours)"].iloc[:2]) == [10, 0] and pd.isna(out.loc[2, "en retard (jours)"])
    assert out.loc[0, "whatsapp"] == "https://wa.me/21620000001"


def test_unscheduled_interested_needs_status_and_no_date():
    wide = _wide([
        ["warm", "20000001", "Intéressé", "", "", ""],
        ["scheduled", "20000002", "Intéressé", "2026-10-20", "", ""],
        ["other", "20000003", "Contacté", "", "", ""]])
    assert list(unscheduled_interested(wide, TODAY)["nom"]) == ["warm"]


def test_near_promotion_band_and_remaining():
    df = pd.DataFrame({
        "nom": ["close", "far", "done", "inactive", "top"], "téléphone": ["20000001"] * 5,
        "grade": ["g"] * 5, "next_grade": ["h"] * 4 + [None],
        "next_objective": [1000.0, 1000.0, 1000.0, 1000.0, None],
        "is_active": [True, True, True, False, True],
        "personal_sales_ttc": [0.0] * 5, "pending_personal_sales_ttc": [0.0] * 5,
        "team_sales_ttc": [800.0, 100.0, 1200.0, 900.0, 50.0], "pending_team_sales_ttc": [0.0] * 5,
        "downline_sales_ttc": [0.0] * 5, "pending_downline_sales_ttc": [0.0] * 5})
    out = near_promotion(df, "Ventes équipe", True)
    assert list(out["nom"]) == ["close"] and out.loc[0, "reste à faire"] == 200.0


def test_inactive_by_impact_ranks_by_branch_size():
    nodes = pd.DataFrame({
        "user_id": [1, 2, 3, 4, 5], "sponsor_id": [None, 1, 2, 1, 5], "name": list("abcde"),
        "grade": ["g"] * 5, "grade_order": [1] * 5, "is_active": [False, False, True, True, False],
        "team_sales": [0.0] * 5, "direct_count": [2, 1, 0, 0, 0]})
    phones = pd.DataFrame({"user_id": [1, 2], "téléphone": ["20000001", None]})
    out = inactive_by_impact(nodes, phones)
    assert list(out["nom"]) == ["a", "b"]                      # e is inactive but has nobody under it
    assert list(out["personnes dans sa branche"]) == [3, 1]
    assert out.loc[0, "whatsapp"] == "https://wa.me/21620000001" and pd.isna(out.loc[1, "whatsapp"])


def test_whatsapp_link_only_for_eight_digit_numbers():
    assert whatsapp_link("20000001") == "https://wa.me/21620000001"
    assert whatsapp_link("123") is None and whatsapp_link(None) is None
