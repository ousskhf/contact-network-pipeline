from datetime import date

import duckdb
import pandas as pd

from app.queries import (METRICS, grade_ladder, progress_vs_objective, progression, upcoming_birthdays,
                         birthdays_source, campaign)


def test_ladder_and_next_objective_from_pipeline(db):
    con = duckdb.connect(db, read_only=True)
    ladder = grade_ladder(con)
    assert list(ladder["grade"]) == ["Bronze", "Silver", "Gold", "Platinum"]
    top = con.execute("select next_grade, next_objective from main.dim_grade where grade = 'Platinum'").fetchone()
    assert top == (None, None)                                   # nothing above the top grade
    row = con.execute("select next_grade, next_objective from main.dim_grade where grade = 'Gold'").fetchone()
    assert row == ("Platinum", 24000.0)
    cam = campaign(con)
    assert cam["name"] == "Campagne démo" and str(cam["start_date"])[:10] == "2026-10-01"
    p = progression(con)
    assert len(p) == 12 and p["grade"].notna().all()
    assert (p["is_promoted"].sum()) == 6                         # fixture: odd members are promoted


def test_progress_vs_objective_picks_metric_and_pending():
    df = pd.DataFrame({
        "nom": ["a", "b", "top"], "next_objective": [900.0, 900.0, None],
        "personal_sales_ttc": [0.0, 0.0, 50.0], "pending_personal_sales_ttc": [0.0, 0.0, 0.0],
        "team_sales_ttc": [450.0, 90.0, 10.0], "pending_team_sales_ttc": [0.0, 90.0, 0.0],
        "downline_sales_ttc": [0.0] * 3, "pending_downline_sales_ttc": [0.0] * 3})
    out = progress_vs_objective(df, "Ventes équipe", include_pending=True)
    assert list(out["nom"]) == ["a", "b", "top"]                  # a 50 %, b 20 %, top has no objective -> last
    assert list(out["% de l'objectif"].iloc[:2]) == [50.0, 20.0] and pd.isna(out["% de l'objectif"].iloc[2])
    only_done = progress_vs_objective(df, "Ventes équipe", include_pending=False)
    assert only_done.set_index("nom").loc["b", "valeur"] == 90.0
    assert {"Ventes perso", "Ventes équipe", "Ventes descendance"} <= set(METRICS)           # original TTC keys kept
    assert {"Ventes perso (HT)", "Ventes équipe (NET)", "Ventes parrainage (TTC)"} <= set(METRICS)  # new variants


def test_upcoming_birthdays_windows_leap_day_and_links():
    df = pd.DataFrame({
        "nom": ["today", "soon", "far", "leap", "nophone"],
        "téléphone": ["20000001", "20000002", "20000003", "20000004", None],
        "grade": ["g"] * 5,
        "birth_date": pd.to_datetime(["1990-10-02", "1985-10-09", "1970-03-01", "1992-02-29", "2000-10-03"]).date})
    out = upcoming_birthdays(df, today=date(2026, 10, 2), within_days=30)
    assert list(out["nom"]) == ["today", "nophone", "soon"]
    assert list(out["dans (jours)"]) == [0, 1, 7] and list(out["âge"]) == [36, 26, 41]
    assert out.loc[0, "whatsapp"] == "https://wa.me/21620000001" and pd.isna(out.loc[1, "whatsapp"])
    # leap day: next occurrence in a non-leap year is Feb 28, and year rollover works in December
    dec = upcoming_birthdays(df, today=date(2026, 12, 20), within_days=100)
    assert dec.set_index("nom").loc["leap", "anniversaire"] == "28/02"
    assert dec.set_index("nom").loc["leap", "dans (jours)"] == 70
    assert len(birthdays_source(_con_with_members())) == 2          # members without a birth date are skipped


def _con_with_members():
    con = duckdb.connect(":memory:")
    con.execute("create table main.fct_network_membership as select * from (values "
                "(1,'a','g',date '1990-01-02'),(2,'b','g',null::date),(3,'c','g',date '1991-05-05')) "
                "t(member_row,name,grade,birth_date)")
    con.execute("create table main.stg_network as select * from (values (1,'20000001'),(2,'20000002'),(3,'20000003')) t(member_row,phone_norm)")
    return con
