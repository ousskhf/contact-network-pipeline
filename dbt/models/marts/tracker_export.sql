-- The contact_tracker sheet, one row per person (+ network members not in contacts).
-- Phones: first three in their own columns, the rest in "Autres numéros" (no cap, nothing dropped).
-- Blank columns are for manual outreach tracking.
with people as (
    select person_id, source_row, c.name, c.country, c.city, c.region, c.street, c.org_name, c.org_title
    from {{ ref('int_contact_person') }} p
    join {{ ref('stg_contacts') }} c using (source_row)
),
attrs as (
    select
        person_id,
        arg_min(name, source_row) filter (where name <> '') as name,
        arg_min(country, source_row) filter (where country is not null) as pays,
        arg_min(region, source_row) filter (where region is not null) as region,
        -- phone exports often hold the town in the street field: with no city and no region it is the town
        arg_min(coalesce(city, case when region is null then street end), source_row)
            filter (where coalesce(city, case when region is null then street end) is not null) as ville,
        arg_min(street, source_row) filter (where street is not null) as adresse,
        arg_min(concat_ws(' - ', org_title, org_name), source_row)
            filter (where org_title is not null or org_name is not null) as profession,
        min(source_row) as first_row
    from people group by person_id
),
emails as (
    select p.person_id, string_agg(distinct e.email, '; ') as email
    from {{ ref('stg_contact_emails') }} e join people p using (source_row)
    group by p.person_id
),
phones as (
    select person_id, phone_norm, is_valid,
           row_number() over (partition by person_id order by not is_valid, pos) as rn
    from (
        select p.person_id, sp.phone_norm, sp.is_valid,
               min(sp.source_row * 100 + cast(regexp_extract(sp.phone_slot, '\d+') as int)) as pos
        from {{ ref('stg_contact_phones') }} sp
        join {{ ref('int_contact_person') }} p using (source_row)
        group by p.person_id, sp.phone_norm, sp.is_valid
    )
),
phone_cols as (
    select person_id,
           max(phone_norm) filter (where rn = 1) as p1,
           max(phone_norm) filter (where rn = 2) as p2,
           max(phone_norm) filter (where rn = 3) as p3,
           string_agg(phone_norm, ' ; ' order by rn) filter (where rn > 3) as autres
    from phones group by person_id
),
net as (
    select person_id,
           arg_min(user_id, member_row) as user_id,
           arg_min(grade, member_row) as grade,
           arg_min(birth_date, member_row) filter (where birth_date is not null) as birth_date,
           arg_min(case when is_active then 'Oui' else 'Non' end, member_row) as actif,
           arg_min(sponsor_name, member_row) as sponsor_name,
           arg_min(direct_count, member_row) as direct_count,
           arg_min(depth, member_row) as depth,
           arg_min(personal_sales_ttc, member_row) as ca_perso_termine,
           arg_min(pending_personal_sales_ttc, member_row) as ca_perso_attente,
           arg_min(team_sales_ttc, member_row) as ca_equipe_termine,
           arg_min(pending_team_sales_ttc, member_row) as ca_equipe_attente,
           arg_min(next_objective, member_row) as objectif_grade,
           arg_min(group_bonus_rate, member_row) as taux_bonus,
           arg_min(next_grade, member_row) as grade_suivant
    from {{ ref('fct_network_membership') }} where person_id is not null group by person_id
),
contacts as (
    select
        a.first_row as sort_key,
        n.user_id,
        coalesce(a.name, '') as "Nom",
        pc.p1 as "Téléphone", pc.p2 as "Téléphone 2", pc.p3 as "Téléphone 3", pc.autres as "Autres numéros",
        e.email as "Email", a.pays as "Pays", a.region as "Région", a.ville as "Ville",
        cast(null as varchar) as "Localité", a.adresse as "Adresse",
        a.profession as "Profession",
        d.aliases as "Alias",
        n.grade as "Grade", n.actif as "Actif", n.birth_date as "Anniversaire",
        n.sponsor_name as "Sponsor", n.direct_count as "Directs", n.depth as "Profondeur",
        n.ca_perso_termine as "CA Personnel Terminé", n.ca_perso_attente as "CA Personnel En Attente",
        n.ca_equipe_termine as "CA Équipe Terminé", n.ca_equipe_attente as "CA Équipe En Attente",
        n.objectif_grade as "Objectif Grade", n.taux_bonus as "Taux Bonus", n.grade_suivant as "Grade Suivant",
        cast(null as varchar) as "Notes"
    from attrs a
    left join phone_cols pc using (person_id)
    left join emails e using (person_id)
    left join net n using (person_id)
    left join {{ ref('dim_person') }} d using (person_id)
),
network_only as (
    select 1000000 + f.member_row as sort_key,
           f.user_id,
           f.name as "Nom",
           s.phone_norm as "Téléphone", s.phone2_norm as "Téléphone 2",
           cast(null as varchar) as "Téléphone 3", cast(null as varchar) as "Autres numéros",
           cast(null as varchar) as "Email", cast(null as varchar) as "Pays", cast(null as varchar) as "Région",
           cast(null as varchar) as "Ville", cast(null as varchar) as "Localité", cast(null as varchar) as "Adresse",
           cast(null as varchar) as "Profession", cast(null as varchar) as "Alias",
           f.grade as "Grade", case when f.is_active then 'Oui' else 'Non' end as "Actif",
           f.birth_date as "Anniversaire",
           f.sponsor_name as "Sponsor", f.direct_count as "Directs", f.depth as "Profondeur",
           f.personal_sales_ttc as "CA Personnel Terminé", f.pending_personal_sales_ttc as "CA Personnel En Attente",
           f.team_sales_ttc as "CA Équipe Terminé", f.pending_team_sales_ttc as "CA Équipe En Attente",
           f.next_objective as "Objectif Grade", f.group_bonus_rate as "Taux Bonus", f.next_grade as "Grade Suivant",
           'Importé du réseau (membre)' as "Notes"
    from {{ ref('fct_network_membership') }} f
    join {{ ref('stg_network') }} s using (member_row)
    where f.person_id is null
)
select
    sort_key,
    user_id,
    "Nom", "Téléphone", "Téléphone 2", "Téléphone 3", "Autres numéros",
    cast(null as varchar) as "Réseau social",
    "Pays", "Région", "Ville", "Localité", "Adresse", cast(null as varchar) as "Genre", cast(null as varchar) as "Langue Préférée",
    cast(null as varchar) as "Comment Connu(e)", cast(null as varchar) as "Recommandé Par",
    cast(null as varchar) as "Statut", cast(null as varchar) as "Type d'Intérêt",
    cast(null as varchar) as "Produit d'Intérêt", cast(null as varchar) as "Contacté Par",
    cast(null as varchar) as "Date de Premier Contact", cast(null as varchar) as "Date de Dernier Contact",
    cast(null as varchar) as "Date de Relance", cast(null as varchar) as "Date de Conversion",
    cast(null as varchar) as "Famille", cast(null as varchar) as "Tranche d'Âge",
    cast(null as varchar) as "Objection/Raison",
    "Email", "Profession", "Grade", "Actif", "Anniversaire",
    "Sponsor", "Directs", "Profondeur",
    "CA Personnel Terminé", "CA Personnel En Attente", "CA Équipe Terminé", "CA Équipe En Attente",
    "Objectif Grade", "Taux Bonus", "Grade Suivant",
    concat_ws(chr(10), "Notes", case when "Alias" is not null then 'Alias(es): ' || "Alias" end) as "Notes"
from (select * from contacts union all by name select * from network_only)
