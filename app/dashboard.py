import os
import sys
from datetime import date
from pathlib import Path

import html as htmllib

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# `streamlit run app/dashboard.py` only puts app/ on the path, so add the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import carte
from app.network_tree import (ancestors, descendant_counts, echarts_html, echarts_tree, grade_colors, index_tree,
                              subtree, treemap_data)
from app.queries import (ALL_STATUSES, METRICS, archived_person_ids, birthdays_source, campaign, connect, due_followups, grade_health,
                         grade_ladder, inactive_by_impact, inactive_members, invalid_numbers, merge_conflicts, merge_report,
                         near_promotion, network_by_grade, network_export, network_members, network_nodes, network_phones, progress_vs_objective,
                         progression, same_number_links, quality_from_rows, summary, tracker, unscheduled_interested, upcoming_birthdays)
from app.trajets import make_stop, resolve_short_link, route_links
from ingest import outreach
from ingest.vcard import to_vcard

st.set_page_config(page_title="Contacts & réseau", layout="wide")
st.title("Contacts & réseau")

try:                       # same host the page was opened from
    host = st.context.headers.get("Host", "localhost").split(":")[0]
except Exception:
    host = "localhost"

with st.sidebar:
    st.markdown(f"**Outils locaux**\n\n- [Airflow](http://{host}:8090) — lancer / planifier le pipeline\n"
                f"- [Docs dbt](http://{host}:8091) — modèles et lignage")
    export = Path(os.environ.get("CNP_EXPORT", "data/contact_tracker.csv"))
    if export.exists():
        st.download_button("Télécharger contact_tracker.csv", export.read_bytes(),
                           file_name="contact_tracker.csv", mime="text/csv")
        st.caption("Le CSV est régénéré par le pipeline (`make run`) et inclut le suivi saisi ici.")
    else:
        st.caption("Pas encore de contact_tracker.csv — lancer le pipeline.")

if not Path(os.environ.get("CNP_DB", "data/cnp.duckdb")).exists():
    st.info("Aucune donnée pour l'instant. Lancer le pipeline : `make run` "
            "(ou déclencher le DAG cnp_refresh dans Airflow).")
    st.stop()

con = connect()
try:
    tr_all = tracker(con)
    net_all = tr_all.pop("_network_only")
    wide_all, orphans = outreach.overlay(tr_all, outreach.load(), notes_column="Notes perso")
    archived = wide_all["Statut"].fillna("").eq(outreach.ARCHIVED)       # kept in the Sheet, ignored below
    gone = archived_person_ids(con, wide_all)
    s = summary(con, gone)
    grades, merges, invalid = network_by_grade(con), merge_report(con, gone), invalid_numbers(con, gone)
    health, inactive = grade_health(con), inactive_members(con)
    conflicts, by_number = merge_conflicts(con, gone), same_number_links(con, gone)
    cam, ladder, prog, born = campaign(con), grade_ladder(con), progression(con), birthdays_source(con)
    nodes, phones, members = network_nodes(con), network_phones(con), network_members(con)
finally:
    con.close()          # never hold the DuckDB file: the pipeline needs to write to it

# Archived contacts are left out of every view except the Suivi tab's "Archivés" list.
wide, tr, network_only = wide_all[~archived], tr_all[~archived], net_all[~archived]
q = {**quality_from_rows(wide), "invalid_numbers": len(invalid)}
prospect_all = tr_all["Grade"].isna() & ~net_all
prospect_mask = prospect_all[~archived]
n_archived = int(archived.sum())


def csv_button(label, df, name):
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), file_name=name, mime="text/csv")


tab_todo, tab_over, tab_net, tab_tree, tab_prog, tab_bday, tab_pros, tab_follow, tab_map, tab_route = st.tabs(
    ["À faire", "Vue d'ensemble", "Réseau", "Arbre du réseau", "Progression", "Anniversaires", "Prospects", "Suivi",
     "Carte", "Trajets"])

WA = {"whatsapp": st.column_config.LinkColumn("whatsapp", display_text="Écrire")}


def action_list(title, caption, df, filename, empty="Rien à signaler."):
    st.subheader(f"{title} ({len(df)})")
    st.caption(caption)
    if df.empty:
        st.caption(empty)
        return
    st.dataframe(df, hide_index=True, width="stretch", column_config=WA)
    csv_button("Télécharger (CSV)", df.drop(columns=["whatsapp"], errors="ignore"), filename)


with tab_todo:
    today = date.today()
    due = due_followups(wide, today)
    warm = unscheduled_interested(wide, today)
    promo = near_promotion(prog, "Ventes équipe", True)
    impact = inactive_by_impact(nodes, phones)
    week = upcoming_birthdays(born, today, 7)
    c = st.columns(5)
    c[0].metric("Relances dues", len(due))
    c[1].metric("Intéressés sans relance", len(warm))
    c[2].metric("Presque promus", len(promo))
    c[3].metric("Inactifs à fort impact", len(impact))
    c[4].metric("Anniversaires (7 j)", len(week))
    st.caption("Listes calculées à partir de tes données du jour. Les liens « Écrire » ouvrent WhatsApp, rien n'est envoyé.")
    action_list("Relances à faire aujourd'hui",
                "Date de relance dépassée ou statut « À relancer » (hors convertis et pas intéressés). À saisir dans l'onglet Suivi.",
                due, "relances.csv")
    action_list("Intéressés sans date de relance",
                "Statut « Intéressé » mais aucune relance prévue : ils risquent d'être oubliés. Fixe une date dans l'onglet Suivi.",
                warm, "interesses.csv")
    action_list("Presque promus",
                "Membres actifs à 60–99 % de l'objectif du grade suivant (ventes équipe, en attente incluses). "
                "Indicatif : la source ne précise pas quelle vente compte. Les aider à finir avant la fin de la campagne.",
                promo, "presque_promus.csv", empty="Personne n'est dans cette zone pour l'instant (ou aucune vente enregistrée).")
    action_list("Inactifs dont dépend une branche",
                "Membres inactifs classés par taille de la branche sous eux : les réactiver ou les remplacer pèse le plus.",
                impact, "inactifs_impact.csv")
    action_list("Anniversaires des 7 prochains jours",
                "Une raison simple d'écrire à quelqu'un du réseau.", week, "anniversaires_7j.csv")

with tab_over:
    c = st.columns(4)
    c[0].metric("Lignes de contacts", s["contact_rows"])
    c[1].metric("Personnes uniques", s["people"], f"-{s['contact_rows'] - s['people']} doublons")
    c[2].metric("Numéros", s["numbers"])
    c[3].metric("Réseau relié aux contacts", f"{s['network_linked']}/{s['network_members']}")

    st.subheader("Qualité des données")
    d = st.columns(4)
    d[0].metric("Numéros invalides", q["invalid_numbers"])
    for col, label, key in ((d[1], "Avec email", "with_email"), (d[2], "Avec ville", "with_town"),
                            (d[3], "Avec profession", "with_profession")):
        col.metric(label, f"{q[key]}/{q['tracker_rows']}")
    if n_archived:
        st.caption(f"{n_archived} contact(s) archivé(s) ignoré(s) partout ici. Ils restent dans le Sheet ; "
                   "pour les restaurer, changer leur statut (onglet Suivi, vue « Archivés »).")
    if not invalid.empty:
        st.caption("Entrées qui ne sont pas des numéros plausibles (codes courts, lettres…) : conservées, jamais utilisées pour fusionner.")
        st.dataframe(invalid, hide_index=True, width="stretch")

    st.subheader("Doublons fusionnés")
    st.caption("Lignes de contacts fusionnées car elles partagent un numéro — à vérifier si deux personnes partagent le même téléphone.")
    st.dataframe(merges, hide_index=True, width="stretch")

    st.subheader("Numéros partagés : à vérifier")
    st.caption("Un numéro n'est pas une personne : des membres donnent le leur à ceux qui les entourent pour les livraisons. "
               "Rien n'est modifié ici, c'est une liste de contrôle.")
    st.markdown(f"**Contacts fusionnés avec des noms différents ({len(conflicts)})**")
    st.caption("Ces fiches ont été fusionnées car elles partagent un numéro, mais leurs noms ne correspondent pas : "
               "deux personnes sur le même téléphone, ou la même personne écrite autrement. "
               "Un seul nom de famille en commun ne compte pas comme une correspondance.")
    if conflicts.empty:
        st.caption("Rien à vérifier (ou le pipeline n'a pas encore été relancé depuis cette fonction).")
    else:
        st.dataframe(conflicts.drop(columns="person_id"), hide_index=True, width="stretch")
        csv_button("Télécharger la liste (CSV)", conflicts.drop(columns="person_id"), "fusions_a_verifier.csv")
    st.markdown(f"**Membres reliés à un contact par le numéro seulement ({len(by_number)})**")
    st.caption("Le numéro est dans tes contacts, mais sous un autre nom : le membre compte comme « déjà dans mes contacts » "
               "sans y être sous son propre nom.")
    if by_number.empty:
        st.caption("Aucun.")
    else:
        st.dataframe(by_number, hide_index=True, width="stretch")

with tab_net:
    total, n_inactive = int(health["total"].sum()), len(inactive)
    c = st.columns(3)
    c[0].metric("Membres du réseau", total)
    c[1].metric("Actifs", total - n_inactive)
    c[2].metric("Inactifs à relancer", n_inactive)
    if health.empty:
        st.caption("Aucun membre du réseau chargé (charger `downline.json`).")
    else:
        st.subheader("Santé du réseau par grade")
        st.caption("Ordre des grades supposé, du plus bas au plus haut.")
        st.bar_chart(health.set_index("grade")[["actifs", "inactifs"]], horizontal=True)
        st.dataframe(health, hide_index=True, width="stretch")
        st.subheader("Membres inactifs à relancer")
        st.dataframe(inactive, hide_index=True, width="stretch")
        csv_button("Télécharger la liste (CSV)", inactive, "inactifs.csv")

        st.subheader("Ajouter des membres aux contacts du téléphone")
        st.caption("Choisir qui ajouter, puis télécharger le fichier .vcf et l'ouvrir sur le téléphone "
                   "(Android : Contacts, Importer). Chaque fiche contient le nom et le numéro, et l'entreprise si elle est "
                   "définie. Sans statut saisi, un membre compte comme « À contacter » (filtre Statut).")
        f = st.columns(4)
        f_status = f[0].multiselect("Statut", outreach.STATUTS, default=list(ALL_STATUSES), key="vc_status")
        f_new = f[1].checkbox("Pas déjà dans mes contacts", value=True, key="vc_new")
        f_active = f[2].selectbox("Activité", ["tous", "actifs", "inactifs"], key="vc_active")
        f_grades = f[3].multiselect("Grade", sorted(members["grade"].dropna().unique()), key="vc_grades",
                                    placeholder="Tous les grades")
        keys_m, _, children_m, order_m = index_tree(nodes)
        desc_m = descendant_counts(children_m, order_m)
        branches = sorted((k for k in keys_m if desc_m[k] > 0), key=lambda k: -desc_m[k])
        f_branch = st.selectbox("Branche", [None] + branches, key="vc_branch",
                                format_func=lambda k: "Tout le réseau" if k is None
                                else f"{keys_m[k].name} — {desc_m[k]} sous lui")
        ids = None if f_branch is None else {int(u) for u in subtree(nodes, int(f_branch))["user_id"].dropna()}
        picked, no_number = network_export(members, wide_all, tuple(f_status), f_new, f_active,
                                           f_grades or None, ids)
        st.metric("Membres à ajouter", len(picked))
        if no_number:
            st.caption(f"{no_number} membre(s) sans numéro de téléphone exploitable, non inclus.")
        if picked.empty:
            st.caption("Aucun membre ne correspond à ces filtres.")
        else:
            st.dataframe(picked, hide_index=True, width="stretch")
            st.download_button("Télécharger les contacts (.vcf)", to_vcard(picked.to_dict("records")).encode("utf-8"),
                               file_name="reseau.vcf", mime="text/vcard")

with tab_tree:
    if nodes.empty:
        st.caption("Aucun membre du réseau chargé (charger `downline.json`).")
    else:
        keys, _, children, order = index_tree(nodes)
        desc = descendant_counts(children, order)
        with_kids = sorted((k for k in keys if desc[k] > 0), key=lambda k: -desc[k])
        pick = st.selectbox("Branche", [None] + with_kids, key="tree_branch",
                            format_func=lambda k: "Tout le réseau" if k is None
                            else f"{keys[k].name} — {desc[k]} sous lui")
        view = nodes if pick is None else subtree(nodes, int(pick))
        if pick is not None:
            st.caption("Chemin : " + " › ".join(ancestors(nodes, int(pick))))
        c = st.columns(3)
        c[0].metric("Membres affichés", len(view))
        c[1].metric("Actifs", int(view["is_active"].sum()))
        c[2].metric("Inactifs", int((~view["is_active"]).sum()))
        palette = grade_colors(nodes)
        st.markdown(" &nbsp; ".join(f"<span style='color:{col}'>●</span> {htmllib.escape(g)}" for g, col in palette.items())
                    + " &nbsp; <span style='color:#b0b5bb'>○</span> inactif", unsafe_allow_html=True)
        st.subheader("Arbre (clic pour ouvrir ou fermer une branche, molette pour zoomer)")
        depth = st.slider("Niveaux ouverts au départ", 1, 5, 2, key="tree_depth")
        # st.components.v1.html is deprecated (st.iframe is the successor but runs same-origin); revisit
        # once the page can be checked in a real browser.
        components.html(echarts_html(echarts_tree(view), height=760, initial_depth=depth), height=780)
        st.subheader("Aperçu : taille des branches")
        st.caption("La surface d'un bloc est proportionnelle au nombre de personnes dans la branche. Clic pour zoomer.")
        levels = st.slider("Niveaux affichés", 2, 6, 3, key="tree_levels")
        t = treemap_data(view)
        fig = go.Figure(go.Treemap(ids=t["ids"], parents=t["parents"], labels=t["labels"], values=t["values"],
                                   branchvalues="remainder", maxdepth=levels,
                                   marker=dict(colors=t["colors"], line=dict(width=1, color="white")),
                                   customdata=t["hover"], hovertemplate="%{customdata}<extra></extra>"))
        fig.update_layout(margin=dict(t=10, l=0, r=0, b=0), height=560)
        st.plotly_chart(fig, width="stretch")

with tab_prog:
    if cam:
        start, end = pd.Timestamp(cam["start_date"]).date(), pd.Timestamp(cam["end_date"]).date()
        left = (end - date.today()).days
        st.info(f"Campagne « {cam['name']} » : du {start:%d/%m/%Y} au {end:%d/%m/%Y} "
                f"({'terminée' if left < 0 else f'{left} jour(s) restant(s)'}).")
    if prog.empty:
        st.caption("Aucun membre du réseau chargé (charger `downline.json`).")
    else:
        confirmed = float(prog[["personal_sales_ttc", "team_sales_ttc", "downline_sales_ttc"]].fillna(0).to_numpy().sum())
        if confirmed == 0:
            st.caption("Aucune vente confirmée enregistrée pour cette campagne : seules les ventes en attente comptent pour l'instant.")
        c = st.columns(3)
        c[0].metric("Promus (selon la source)", int(prog["is_promoted"].fillna(False).sum()))
        c[1].metric("Grade éligible renseigné", int(prog["eligible_grade"].notna().sum()))
        c[2].metric("Actifs avec ventes en attente",
                    int(((prog["pending_personal_sales_ttc"].fillna(0) + prog["pending_team_sales_ttc"].fillna(0)) > 0).sum()))
        st.subheader("Échelle des grades (publiée par la source)")
        st.dataframe(ladder, hide_index=True, width="stretch")
        st.subheader("Où en est chaque membre")
        st.caption("La source ne précise pas quelle vente mesure l'objectif d'un grade : choisis la mesure comparée. "
                   "Le pourcentage est indicatif, pas la règle officielle de passage.")
        f1, f2, f3 = st.columns(3)
        metric = f1.selectbox("Mesure comparée à l'objectif", list(METRICS), index=1)   # "Ventes équipe"
        pending = f2.checkbox("Inclure les ventes en attente", value=True)
        active_only = f3.checkbox("Actifs seulement", value=True)
        pv = progress_vs_objective(prog[prog["is_active"]] if active_only else prog, metric, pending)
        view_cols = ["nom", "téléphone", "grade", "next_grade", "next_objective", "valeur", "% de l'objectif",
                     "is_promoted", "eligible_grade", "direct_count", "sponsor_name"]
        pv_view = pv[view_cols].rename(columns={"next_grade": "grade suivant", "next_objective": "objectif publié",
                                                "is_promoted": "promu", "eligible_grade": "éligible (source)",
                                                "direct_count": "directs", "sponsor_name": "sponsor"})
        st.dataframe(pv_view, hide_index=True, width="stretch")
        csv_button("Télécharger (CSV)", pv_view, "progression.csv")

with tab_bday:
    if born.empty:
        st.caption("Aucune date de naissance disponible (charger `downline.json`).")
    else:
        horizon = st.radio("Horizon", [7, 30, 90], index=1, horizontal=True, format_func=lambda d: f"{d} jours")
        ub = upcoming_birthdays(born, date.today(), horizon)
        c = st.columns(3)
        c[0].metric("Aujourd'hui", int((ub["dans (jours)"] == 0).sum()))
        c[1].metric("Cette semaine", int((ub["dans (jours)"] <= 7).sum()))
        c[2].metric(f"Dans {horizon} jours", len(ub))
        st.caption("Membres du réseau uniquement (les contacts du téléphone n'ont pas de date de naissance). "
                   "Le lien WhatsApp ouvre une conversation, rien n'est envoyé.")
        st.dataframe(ub, hide_index=True, width="stretch",
                     column_config={"whatsapp": st.column_config.LinkColumn("whatsapp", display_text="Écrire")})
        csv_button("Télécharger (CSV)", ub.drop(columns=["whatsapp"]), "anniversaires.csv")

with tab_pros:
    pros = wide[prospect_mask][["Nom", "Téléphone", *outreach.LOCATION_FIELDS, "Profession", "Email", "Statut"]]
    c = st.columns(3)
    c[0].metric("Prospects (contacts hors réseau)", len(pros))
    c[1].metric("Déjà dans le réseau", int((~prospect_mask & ~network_only).sum()))
    c[2].metric("Déjà contactés", int(pros["Statut"].fillna("").ne("").sum()))
    st.caption("Contacts de ton téléphone qui ne sont pas dans le réseau. Le statut se saisit dans l'onglet Suivi.")
    f1, f2 = st.columns(2)
    text = f1.text_input("Rechercher (nom, ville…)", key="pros_search")
    only_new = f2.checkbox("Seulement ceux pas encore contactés", value=True)
    shown = pros[pros["Statut"].fillna("").eq("")] if only_new else pros
    if text:
        blob = shown.fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        shown = shown[blob.str.contains(text.lower(), regex=False)]
    st.dataframe(shown, hide_index=True, width="stretch")
    csv_button("Télécharger les prospects (CSV)", shown, "prospects.csv")

with tab_follow:
    st.caption("Saisie du suivi (statut, dates, notes). Enregistré dans `data/outreach.duckdb`, relié aux personnes par "
               "leur numéro, et inclus dans `contact_tracker.csv` à chaque exécution du pipeline. **Sauvegarde ce fichier.**")
    if orphans:
        st.warning(f"{orphans} entrée(s) de suivi ne correspondent plus à aucun contact (numéro disparu).")
    f1, f2, f3 = st.columns([2, 2, 1])
    view = f1.radio("Afficher", ["Tous", "Prospects", "Réseau", "Archivés"], horizontal=True)
    text = f2.text_input("Rechercher", key="follow_search")
    more = f3.toggle("Tous les champs")

    data = wide_all.drop(columns=["Notes"]).rename(columns={"Notes perso": "Notes"})   # editor edits only your own notes
    fields = outreach.MAIN_FIELDS + (outreach.MORE_FIELDS if more else [])
    shown_cols = ["Nom", "Téléphone", "Grade"] + fields
    mask = {"Tous": ~archived, "Prospects": prospect_all & ~archived, "Réseau": tr_all["Grade"].notna() & ~archived,
            "Archivés": archived}[view]
    if view == "Archivés":
        st.caption("Contacts archivés : ignorés dans toute l'application mais gardés dans le Sheet. "
                   "Pour en restaurer un, changer son statut puis enregistrer.")
    sub = data.loc[mask, shown_cols].copy()
    if text:
        blob = sub[["Nom", "Téléphone"]].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        sub = sub[blob.str.contains(text.lower(), regex=False)]
    for f in outreach.DATE_FIELDS:
        sub[f] = pd.to_datetime(sub[f], errors="coerce").dt.date
    config = {"Statut": st.column_config.SelectboxColumn("Statut", options=outreach.STATUTS)}
    config.update({f: st.column_config.DateColumn(f) for f in outreach.DATE_FIELDS})
    st.caption(f"{len(sub)} ligne(s)")
    edited = st.data_editor(sub, hide_index=True, width="stretch", key=f"editor_{view}_{more}",
                            disabled=["Nom", "Téléphone", "Grade"], column_config=config)

    if st.button("Enregistrer", type="primary"):
        keys = tr_all.apply(lambda r: outreach.row_key(r.to_dict()), axis=1)
        changes = outreach.collect_changes(edited, sub, data, keys, fields)
        if changes:
            outreach.save(changes)
            st.success(f"{len(changes)} ligne(s) enregistrée(s).")
            st.rerun()
        else:
            st.info("Aucune modification.")


@st.cache_data(ttl=86400, show_spinner=False)
def follow_short_link(url):
    return resolve_short_link(url)


with tab_map:
    group = st.radio("Afficher", ["Tout le monde", "Membres du réseau", "Prospects"], horizontal=True, key="map_group")
    in_group = {"Tout le monde": pd.Series(True, index=wide.index), "Membres du réseau": wide["Grade"].notna(),
                "Prospects": wide["Grade"].isna()}[group]
    folk = wide[in_group][["Nom", "Téléphone", "Grade", "Statut", "Pays", "Région", "Ville"]]
    regions = carte.by_region(folk)
    abroad = int(folk["Pays"].map(carte.is_abroad).sum())
    m = st.columns(3)
    m[0].metric("Sur la carte", f"{int(regions['Personnes'].sum())}/{len(folk)}")
    m[1].metric("Régions représentées", len(regions))
    m[2].metric("À l'étranger", abroad)
    st.caption("Chaque cercle est le centre d'une région (gouvernorat), pas une adresse : on compte les personnes, "
               "on ne montre aucun domicile. La région vient de la colonne Région du Sheet, à défaut de la Ville.")

    if regions.empty:
        st.info("Personne n'a encore de région ou de ville reconnue. Elles se saisissent dans le Sheet "
                "(colonnes Région, Ville), puis `make sync`.")
    else:
        top = float(regions["Personnes"].max())
        fig = go.Figure(go.Scattergeo(
            lat=regions["lat"], lon=regions["lon"], mode="markers+text", text=regions["Personnes"].astype(str),
            customdata=regions["Région"], hovertemplate="%{customdata}: %{text} personne(s)<extra></extra>",
            marker=dict(size=14 + 40 * (regions["Personnes"] / top) ** 0.5, color="#2a7ab9", opacity=0.75,
                        line=dict(width=1, color="white")),
            textfont=dict(color="white", size=11)))
        fig.update_geos(lonaxis_range=[7.3, 11.9], lataxis_range=[30.1, 37.6], resolution=50, showcountries=True,
                        showland=True, landcolor="rgba(128,128,128,0.15)", showocean=False, showframe=False,
                        bgcolor="rgba(0,0,0,0)")
        fig.update_layout(height=620, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")

        left, right = st.columns(2)
        left.subheader("Par région")
        left.dataframe(regions[["Région", "Personnes"]], hide_index=True, width="stretch")
        right.subheader("Par ville")
        villes = carte.by_ville(folk)
        if villes.empty:
            right.caption("Aucune ville saisie.")
        else:
            right.dataframe(villes, hide_index=True, width="stretch")

    if abroad:
        st.subheader("Pays")
        st.dataframe(carte.countries(folk), hide_index=True, width="stretch")

    todo_place = carte.unplaced(folk)
    st.subheader(f"À localiser ({len(todo_place)})")
    st.caption("Personnes sans région reconnue, hors étranger. « Texte non reconnu » : une région ou une ville est "
               "saisie mais ne correspond à aucun gouvernorat connu (ex. « Sahel ») ; à corriger dans le Sheet.")
    if todo_place.empty:
        st.caption("Tout le monde est localisé.")
    else:
        shown_cols = ["Nom", "Téléphone", "Grade", "Statut", "Région", "Ville", "Raison"]
        st.dataframe(todo_place[shown_cols].sort_values(["Raison", "Nom"], ascending=[False, True]),
                     hide_index=True, width="stretch", height=320)
        csv_button("Télécharger (CSV)", todo_place[shown_cols], "a_localiser.csv")

with tab_route:
    st.caption("Choisis les personnes à visiter : un lien Google Maps s'ouvre sur le téléphone avec le trajet, "
               "au départ de la position du téléphone. Les adresses se saisissent dans le Sheet (colonnes Adresse, "
               "Localité, Ville). Dans Adresse, on peut coller un lien Google Maps ou des coordonnées (36.80, 10.18) : "
               "c'est plus précis qu'un texte.")
    r1, r2, r3 = st.columns([2, 2, 1])
    r_text = r1.text_input("Rechercher", key="route_search")
    r_villes = sorted({str(v).strip() for v in wide["Ville"].dropna() if str(v).strip()})
    r_ville = r2.multiselect("Ville", r_villes, key="route_ville", placeholder="Toutes les villes")
    r_only = r3.toggle("Avec adresse seulement", value=True, key="route_only")

    people = wide[["Nom", "Téléphone", "Grade", "Statut", "Ville", "Localité", "Adresse", "Région", "Pays"]].copy()
    people["_key"] = wide.apply(lambda r: outreach.row_key(r.to_dict()), axis=1)
    people["_has_address"] = (people["Adresse"].fillna("").astype(str).str.strip() != "") | \
                             (people["Localité"].fillna("").astype(str).str.strip() != "")
    st.caption(f"{int(people['_has_address'].sum())} personne(s) sur {len(people)} ont une adresse ou une localité.")

    shown = people
    if r_only:
        shown = shown[shown["_has_address"]]
    if r_ville:
        shown = shown[shown["Ville"].isin(r_ville)]
    if r_text:
        blob = shown[["Nom", "Téléphone", "Ville", "Localité"]].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        shown = shown[blob.str.contains(r_text.lower(), regex=False)]
    shown = shown.sort_values(["Ville", "Localité", "Nom"], key=lambda c: c.fillna("").astype(str).str.lower())

    chosen_keys = st.session_state.setdefault("route_sel", set())
    table = shown[["Nom", "Ville", "Localité", "Adresse", "Téléphone", "Statut"]].copy()
    table.insert(0, "Choisir", shown["_key"].isin(chosen_keys).to_numpy())
    st.caption(f"{len(table)} personne(s) affichée(s)")
    edited = st.data_editor(table, hide_index=True, width="stretch",
                            key=f"route_editor_{r_text}_{'|'.join(r_ville)}_{r_only}",
                            disabled=[c for c in table.columns if c != "Choisir"],
                            column_config={"Choisir": st.column_config.CheckboxColumn("Choisir")})
    ticked = set(shown["_key"][edited["Choisir"].to_numpy()])
    chosen_keys = (chosen_keys - set(shown["_key"])) | ticked
    st.session_state["route_sel"] = chosen_keys

    picked = people[people["_key"].isin(chosen_keys)].sort_values(
        ["Ville", "Localité", "Nom"], key=lambda c: c.fillna("").astype(str).str.lower())
    c1, c2 = st.columns([4, 1])
    c1.subheader(f"Trajet ({len(picked)} personne(s) choisie(s))")
    if c2.button("Vider la sélection"):
        st.session_state["route_sel"] = set()
        st.rerun()
    stops, no_stop = [], []
    for r in picked.itertuples():
        stop, problem = make_stop(r.Adresse, r.Localité, r.Ville, r.Région, r.Pays, resolve=follow_short_link)
        (stops if stop else no_stop).append((r.Nom, stop or problem))
    if no_stop:
        st.warning("Sans arrêt exploitable : " + " ; ".join(f"{nom} ({why})" for nom, why in no_stop))
    if stops:
        st.caption("Ordre des arrêts : par ville puis localité. Google Maps ne le réorganise pas.")
        st.dataframe(pd.DataFrame({"#": range(1, len(stops) + 1), "Nom": [n for n, _ in stops],
                                   "Arrêt envoyé à Maps": [s for _, s in stops]}), hide_index=True, width="stretch")
        links = route_links([s for _, s in stops])
        for i, link in enumerate(links, 1):
            label = "Ouvrir le trajet dans Google Maps" if len(links) == 1 else f"Trajet {i}/{len(links)}"
            st.link_button(label, link, type="primary")
        if len(links) > 1:
            st.caption("Une liste longue est coupée en plusieurs liens : chacun démarre là où le précédent finit.")

