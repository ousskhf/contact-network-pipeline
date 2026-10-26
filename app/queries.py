"""Read-only queries over the dbt marts, kept separate from the UI so they can be tested."""
import calendar
import os
from datetime import date

import duckdb
import pandas as pd

from ingest import outreach


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(os.environ.get("CNP_DB", "data/cnp.duckdb"), read_only=True)


def _ids(exclude) -> list[int]:
    return [int(i) for i in exclude]


def archived_person_ids(con, wide) -> list[int]:
    """Warehouse person ids of the contacts whose status is Archivé (matched through any of their numbers)."""
    rows = wide[wide["Statut"].fillna("") == outreach.ARCHIVED]
    numbers = sorted({n for r in rows.to_dict("records") for n in outreach.numbers(r)})
    if not numbers:
        return []
    return [r[0] for r in con.execute("select distinct person_id from main.bridge_person_phone "
                                      "where list_contains(?::VARCHAR[], phone_norm)", [numbers]).fetchall()]


def summary(con, exclude=()) -> dict:
    """Counts over the warehouse, leaving out the archived people (`exclude`: their person ids)."""
    ids = _ids(exclude)
    rows, phones, people = con.execute(
        "select coalesce(sum(n_source_rows), 0), coalesce(sum(n_phones), 0), count(*) "
        "from main.dim_person where list_contains(?::BIGINT[], person_id)", [ids]).fetchone()
    return {
        "contact_rows": con.execute("select count(*) from main.stg_contacts").fetchone()[0] - int(rows),
        "people": con.execute("select count(*) from main.dim_person").fetchone()[0] - int(people),
        "numbers": con.execute("select count(*) from main.bridge_person_phone").fetchone()[0] - int(phones),
        "network_members": con.execute("select count(*) from main.fct_network_membership").fetchone()[0],
        "network_linked": con.execute(
            "select count(*) from main.fct_network_membership where person_id is not null "
            "and not list_contains(?::BIGINT[], person_id)", [ids]).fetchone()[0],
    }


def network_by_grade(con):
    return con.execute(
        "select coalesce(grade, 'Inconnu') as grade, "
        "count(*) filter (where is_active) as actifs, "
        "count(*) filter (where not is_active) as inactifs "
        "from main.fct_network_membership group by 1 order by count(*) desc"
    ).df()


def merge_report(con, exclude=()):
    return con.execute(
        "select person_id, n_rows, source_rows, names from main.merge_audit "
        "where not list_contains(?::BIGINT[], person_id) order by n_rows desc, person_id", [_ids(exclude)]
    ).df()


def _optional(con, sql, params, columns):
    """A model added after the last pipeline run is not in the warehouse yet: show an empty list, not a crash."""
    try:
        return con.execute(sql, params).df()
    except duckdb.CatalogException:
        return pd.DataFrame(columns=columns)


def merge_conflicts(con, exclude=()):
    """Merged contact people whose rows carry names that do not match: different people on one number, or one
    person spelled differently."""
    return _optional(
        con, "select person_id, n_name_conflicts as conflits, n_rows as lignes, names as noms "
             "from main.merge_review where names_conflict and not list_contains(?::BIGINT[], person_id) "
             "order by n_name_conflicts desc, person_id", [_ids(exclude)], ["person_id", "conflits", "lignes", "noms"])


def same_number_links(con, exclude=()):
    """Network members linked to a contact only because they share a number, not because the names fit.
    Grade/sponsor/direct_count are included so a human reviewing the link has enough context to judge it."""
    return _optional(
        con, "select f.name as membre, concat_ws(' | ', d.name, d.aliases) as \"contact avec ce numéro\", "
             "(select max(p.n_members) from main.phone_share p where p.phone_norm in (s.phone_norm, s.phone2_norm)) "
             "as \"membres sur ce numéro\", "
             "coalesce(f.grade, 'Inconnu') as grade, f.sponsor_name as sponsor, f.direct_count as directs "
             "from main.fct_network_membership f join main.dim_person d using (person_id) "
             "join main.stg_network s using (member_row) "
             "where f.link_kind = 'same_number' and not list_contains(?::BIGINT[], f.person_id) "
             "order by f.member_row", [_ids(exclude)],
        ["membre", "contact avec ce numéro", "membres sur ce numéro", "grade", "sponsor", "directs"])


def quality(con) -> dict:
    return {
        "invalid_numbers": con.execute("select count(*) from main.bridge_person_phone where not is_valid").fetchone()[0],
        "tracker_rows": con.execute("select count(*) from main.tracker_export").fetchone()[0],
        "with_email": con.execute('select count(*) from main.tracker_export where "Email" is not null').fetchone()[0],
        "with_town": con.execute('select count(*) from main.tracker_export where "Ville" is not null').fetchone()[0],
        "with_profession": con.execute('select count(*) from main.tracker_export where "Profession" is not null').fetchone()[0],
    }


def quality_from_rows(df) -> dict:
    """Same figures as quality(), computed on the tracker rows (so archived people can be left out)."""
    has = lambda col: int(df[col].fillna("").astype(str).ne("").sum())
    return {"tracker_rows": len(df), "with_email": has("Email"), "with_town": has("Ville"),
            "with_profession": has("Profession")}


def invalid_numbers(con, exclude=()):
    return con.execute(
        "select d.name as nom, b.phone_norm as entrée from main.bridge_person_phone b "
        "join main.dim_person d using (person_id) where not b.is_valid "
        "and not list_contains(?::BIGINT[], person_id) order by d.person_id", [_ids(exclude)]
    ).df()


GRADE_ORDER = ["Bronze", "Silver", "Gold Junior", "Gold",
               "Gold Senior", "Gold Expert", "Platinum"]   # assumed low -> high


def grade_health(con):
    df = con.execute(
        "select coalesce(grade, 'Inconnu') as grade, count(*) filter (where is_active) as actifs, "
        "count(*) filter (where not is_active) as inactifs, count(*) as total "
        "from main.fct_network_membership group by 1").df()
    df["taux actifs"] = (100 * df["actifs"] / df["total"]).round(0).astype(int).astype(str) + " %"
    rank = {g: i for i, g in enumerate(GRADE_ORDER)}
    return df.sort_values("grade", key=lambda s: s.map(lambda g: rank.get(g, 99))).reset_index(drop=True)


def inactive_members(con):
    return con.execute(
        "select f.name as nom, s.phone_norm as téléphone, f.grade, "
        "case when f.person_id is not null then 'oui' else 'non' end as \"dans mes contacts\" "
        "from main.fct_network_membership f join main.stg_network s using (member_row) "
        "where not f.is_active order by f.grade, f.name").df()


def tracker(con):
    """Full tracker, plus flags used by the prospects view."""
    df = con.execute("select * exclude (sort_key) from main.tracker_export order by sort_key").df()
    df["_network_only"] = df["Notes"].fillna("").str.startswith("Importé du réseau")
    return df


# TTC entries keep their original labels (dashboard.py and tests reference them by name);
# HT/NET/parrainage are new, additive.
METRICS = {"Ventes perso": ("personal_sales_ttc", "pending_personal_sales_ttc"),
           "Ventes équipe": ("team_sales_ttc", "pending_team_sales_ttc"),
           "Ventes descendance": ("downline_sales_ttc", "pending_downline_sales_ttc"),
           "Ventes perso (HT)": ("personal_sales_ht", "pending_personal_sales_ht"),
           "Ventes perso (NET)": ("personal_sales_net", "pending_personal_sales_net"),
           "Ventes équipe (HT)": ("team_sales_ht", "pending_team_sales_ht"),
           "Ventes équipe (NET)": ("team_sales_net", "pending_team_sales_net"),
           "Ventes descendance (HT)": ("downline_sales_ht", "pending_downline_sales_ht"),
           "Ventes descendance (NET)": ("downline_sales_net", "pending_downline_sales_net"),
           "Ventes parrainage (TTC)": ("parainage_sales_ttc", "pending_parainage_sales_ttc"),
           "Ventes parrainage (HT)": ("parainage_sales_ht", "pending_parainage_sales_ht"),
           "Ventes parrainage (NET)": ("parainage_sales_net", "pending_parainage_sales_net")}


def campaign(con):
    df = con.execute("select name, start_date, end_date, is_active from main.dim_campaign limit 1").df()
    return df.iloc[0].to_dict() if len(df) else None


def grade_ladder(con):
    return con.execute(
        "select grade, objective as \"objectif publié\", min_vente_perso as \"vente perso min\", "
        "required_confirmed_directors as \"directeurs confirmés requis\", "
        "group_bonus_rate as \"taux bonus groupe\", personal_discount as \"remise perso\", "
        "sponsor_bonus_rate as \"taux bonus parrainage\" "
        "from main.dim_grade order by sort_order").df()


def progression(con):
    return con.execute(
        "select f.name as nom, s.phone_norm as téléphone, f.grade, f.next_grade, f.next_objective, "
        "f.grade_at_start_name, f.is_promoted, f.eligible_grade, f.direct_count, f.depth, f.is_active, "
        "f.sponsor_name, f.group_bonus_rate, "
        "f.personal_sales_ttc, f.pending_personal_sales_ttc, "
        "f.personal_sales_ht, f.pending_personal_sales_ht, f.personal_sales_net, f.pending_personal_sales_net, "
        "f.team_sales_ttc, f.pending_team_sales_ttc, "
        "f.team_sales_ht, f.pending_team_sales_ht, f.team_sales_net, f.pending_team_sales_net, "
        "f.downline_sales_ttc, f.pending_downline_sales_ttc, "
        "f.downline_sales_ht, f.pending_downline_sales_ht, f.downline_sales_net, f.pending_downline_sales_net, "
        "f.parainage_sales_ttc, f.pending_parainage_sales_ttc, "
        "f.parainage_sales_ht, f.pending_parainage_sales_ht, f.parainage_sales_net, f.pending_parainage_sales_net "
        "from main.fct_network_membership f join main.stg_network s using (member_row)").df()


def network_nodes(con):
    return con.execute(
        "select f.user_id, f.sponsor_id, f.name, f.grade, f.grade_order, f.is_active, "
        "coalesce(f.team_sales_ttc, 0) + coalesce(f.pending_team_sales_ttc, 0) as team_sales, f.direct_count, "
        "s.phone_norm as phone "
        "from main.fct_network_membership f join main.stg_network s using (member_row)").df()


def network_members(con):
    """Every network member with the numbers and the contact link used to export them to a phone."""
    return con.execute(
        "select f.user_id, f.sponsor_id, f.name, f.grade, f.is_active, f.person_id, f.link_kind, "
        "s.phone_norm, s.phone2_norm "
        "from main.fct_network_membership f join main.stg_network s using (member_row) order by f.member_row").df()


def birthdays_source(con):
    return con.execute(
        "select f.name as nom, s.phone_norm as téléphone, f.grade, f.birth_date "
        "from main.fct_network_membership f join main.stg_network s using (member_row) "
        "where f.birth_date is not null").df()


def progress_vs_objective(df, metric: str, include_pending: bool):
    """Chosen sales figure against the next grade's published objective. The objective does not say
    which sales it measures, so the figure is the caller's choice; the ratio is indicative only."""
    done, pending = METRICS[metric]
    out = df.copy()
    out["valeur"] = out[done].fillna(0) + (out[pending].fillna(0) if include_pending else 0)
    obj = out["next_objective"].where(out["next_objective"] > 0)
    out["% de l'objectif"] = (100 * out["valeur"] / obj).round(0)
    return out.sort_values(["% de l'objectif", "valeur"], ascending=False, na_position="last").reset_index(drop=True)


def _next_occurrence(born: date, today: date) -> date:
    def on(year):
        day = 28 if (born.month, born.day) == (2, 29) and not calendar.isleap(year) else born.day
        return date(year, born.month, day)
    n = on(today.year)
    return n if n >= today else on(today.year + 1)


def upcoming_birthdays(df, today: date, within_days: int = 30):
    rows = []
    for r in df.itertuples():
        born = pd.Timestamp(r.birth_date).date()
        nxt = _next_occurrence(born, today)
        days = (nxt - today).days
        if days <= within_days:
            phone = r.téléphone if isinstance(r.téléphone, str) else ""
            rows.append({"nom": r.nom, "téléphone": phone, "grade": r.grade, "anniversaire": nxt.strftime("%d/%m"),
                         "dans (jours)": days, "âge": nxt.year - born.year,
                         "whatsapp": f"https://wa.me/216{phone}" if phone.isdigit() and len(phone) == 8 else None})
    out = pd.DataFrame(rows, columns=["nom", "téléphone", "grade", "anniversaire", "dans (jours)", "âge", "whatsapp"])
    return out.sort_values(["dans (jours)", "nom"]).reset_index(drop=True)


def whatsapp_link(phone):
    """wa.me link for an 8-digit Tunisian number; it only opens a chat, nothing is sent."""
    return f"https://wa.me/216{phone}" if isinstance(phone, str) and phone.isdigit() and len(phone) == 8 else None


def network_phones(con):
    return con.execute(
        "select f.user_id, s.phone_norm as téléphone from main.fct_network_membership f "
        "join main.stg_network s using (member_row)").df()


CLOSED = ("Converti", "Pas intéressé", outreach.ARCHIVED)
ACTION_COLUMNS = ["nom", "téléphone", "statut", "intérêt", "relance prévue", "en retard (jours)", "dernier contact", "whatsapp"]


def _outreach_view(wide, mask, today):
    df = wide[mask]
    relance = pd.to_datetime(df["Date de Relance"], errors="coerce")
    out = pd.DataFrame({
        "nom": df["Nom"], "téléphone": df["Téléphone"], "statut": df["Statut"].replace("", None),
        "intérêt": df["Produit d'Intérêt"].replace("", None),
        "relance prévue": relance.dt.date,
        "en retard (jours)": (pd.Timestamp(today) - relance).dt.days,
        "dernier contact": pd.to_datetime(df["Date de Dernier Contact"], errors="coerce").dt.date,
        "whatsapp": df["Téléphone"].map(whatsapp_link)})
    return out[ACTION_COLUMNS]


def due_followups(wide, today: date):
    """People whose follow-up date is today or past, or whose status is 'À relancer', most overdue first."""
    status = wide["Statut"].fillna("")
    relance = pd.to_datetime(wide["Date de Relance"], errors="coerce")
    mask = ~status.isin(CLOSED) & ((relance <= pd.Timestamp(today)) | (status == "À relancer"))
    out = _outreach_view(wide, mask, today)
    return out.sort_values(["en retard (jours)", "nom"], ascending=[False, True], na_position="last").reset_index(drop=True)


def unscheduled_interested(wide, today: date):
    """People marked 'Intéressé' with no follow-up date: warm leads nobody is scheduled to call back."""
    mask = (wide["Statut"].fillna("") == "Intéressé") & pd.to_datetime(wide["Date de Relance"], errors="coerce").isna()
    return _outreach_view(wide, mask, today).sort_values("nom").reset_index(drop=True)


def near_promotion(prog, metric: str, include_pending: bool, min_pct: int = 60):
    """Active members between min_pct and 100 % of the next grade's published objective, closest first.
    Indicative only (see progress_vs_objective)."""
    pv = progress_vs_objective(prog[prog["is_active"]], metric, include_pending)
    pct = pv["% de l'objectif"]
    out = pv[(pct >= min_pct) & (pct < 100)].copy()
    out["reste à faire"] = (out["next_objective"] - out["valeur"]).round(0)
    out["whatsapp"] = out["téléphone"].map(whatsapp_link)
    return out[["nom", "téléphone", "grade", "next_grade", "valeur", "next_objective", "% de l'objectif",
                "reste à faire", "whatsapp"]].rename(columns={"next_grade": "grade suivant", "next_objective": "objectif publié"}
                                                     ).reset_index(drop=True)


def inactive_by_impact(nodes, phones):
    """Inactive members ranked by the size of the branch under them (and its sales): the ones whose
    reactivation or replacement matters most."""
    from app.network_tree import descendant_counts, index_tree
    keys, _, children, order = index_tree(nodes)
    desc = descendant_counts(children, order)
    phone_of = dict(zip(phones["user_id"], phones["téléphone"]))
    rows = []
    for k, r in keys.items():
        if r.is_active:
            continue
        phone = phone_of.get(r.user_id) if pd.notna(r.user_id) else None
        phone = phone if isinstance(phone, str) else None
        rows.append({"nom": r.name, "téléphone": phone, "grade": r.grade, "personnes dans sa branche": desc[k],
                     "directs": r.direct_count, "ventes équipe": r.team_sales, "whatsapp": whatsapp_link(phone)})
    out = pd.DataFrame(rows, columns=["nom", "téléphone", "grade", "personnes dans sa branche", "directs",
                                      "ventes équipe", "whatsapp"])
    out = out[(out["personnes dans sa branche"] > 0) | (out["ventes équipe"] > 0)]
    return out.sort_values(["personnes dans sa branche", "ventes équipe"], ascending=False).reset_index(drop=True)


ALL_STATUSES = tuple(outreach.STATUTS)     # default export filter: everyone; no stored status counts as "À contacter"


def _status_lookup(wide) -> dict:
    """number key -> status, for the tracker rows (a network-only member is keyed by phone#name)."""
    out = {}
    for row in wide.to_dict("records"):
        status = row.get("Statut")
        status = status if isinstance(status, str) and status else "À contacter"
        for n in outreach.numbers(row):
            out.setdefault(n, status)
    return out


def network_export(members, wide, statuses=ALL_STATUSES, only_new=True, active="tous", grades=None, user_ids=None):
    """Network members to add to a phone. Returns (people, n_without_number).

    people: DataFrame nom, téléphone, grade, actif, statut. `wide` must hold every tracker row,
    archived ones included, so an archived person is found and filtered out by status.
    only_new: leave out members already in the phone contacts (linked to a contact by number) --
    but a member linked only because they share a number with someone else's contact
    (link_kind == 'same_number') is not that contact, so they're still offered, under their own name.
    active: "tous", "actifs" or "inactifs". grades / user_ids: keep only these (None = no filter)."""
    lookup = _status_lookup(wide)
    rows, no_number = [], 0
    for m in members.itertuples():
        if only_new and pd.notna(m.person_id) and m.link_kind != "same_number":
            continue
        if active != "tous" and bool(m.is_active) != (active == "actifs"):
            continue
        grade = m.grade if isinstance(m.grade, str) else "Inconnu"
        if grades is not None and grade not in grades:
            continue
        if user_ids is not None and not (pd.notna(m.user_id) and int(m.user_id) in user_ids):
            continue
        phone = next((p for p in (m.phone_norm, m.phone2_norm) if isinstance(p, str) and p), None)
        name = str(m.name or "").strip()
        keys = [f"{p}#{name.lower()}" for p in (m.phone_norm, m.phone2_norm) if isinstance(p, str) and p]
        keys += [p for p in (m.phone_norm, m.phone2_norm) if isinstance(p, str) and p]
        status = next((lookup[k] for k in keys if k in lookup), "À contacter")
        if status not in statuses:
            continue
        if phone is None or not name:
            no_number += 1
            continue
        rows.append({"nom": name, "téléphone": phone, "grade": grade,
                     "actif": "actif" if m.is_active else "inactif", "statut": status})
    cols = ["nom", "téléphone", "grade", "actif", "statut"]
    return pd.DataFrame(rows, columns=cols), no_number
