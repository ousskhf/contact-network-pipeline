-- Network members, linked to a contact person when either number matches (valid numbers only).
-- link_kind: 'name_match' when the contact's name fits the member's, 'same_number' when only the number does
-- (shared numbers: someone else's contact), null when there is no link.
-- Grain is user_id (stable, from the source system) -- member_row (a row_number(), unstable across reloads) is
-- kept only as a legacy ordinal for anything still sorting by load order.
with base as (
select
    n.member_row, n.name, n.user_id, n.sponsor_id, sp.name as sponsor_name,
    coalesce(g.grade, n.grade) as grade,
    n.is_active, n.boutique_code, n.numero_membre,
    n.personal_sales_ttc, n.team_sales_ttc,
    n.pending_personal_sales_ttc, n.pending_team_sales_ttc,
    n.personal_sales_ht, n.pending_personal_sales_ht, n.personal_sales_net, n.pending_personal_sales_net,
    n.team_sales_ht, n.pending_team_sales_ht, n.team_sales_net, n.pending_team_sales_net,
    n.downline_sales_ttc, n.pending_downline_sales_ttc,
    n.downline_sales_ht, n.pending_downline_sales_ht, n.downline_sales_net, n.pending_downline_sales_net,
    n.parainage_sales_ttc, n.pending_parainage_sales_ttc,
    n.parainage_sales_ht, n.pending_parainage_sales_ht, n.parainage_sales_net, n.pending_parainage_sales_net,
    n.birth_date, n.depth, n.direct_count, n.total_excluding_director_networks, n.personal_referrals,
    ga.grade as grade_at_start_name,
    n.is_promoted,
    el.grade as eligible_grade,
    g.sort_order as grade_order, g.next_grade, g.next_objective,
    g.group_bonus_rate, g.personal_discount, g.sponsor_bonus_rate,
    n.email, n.reference, n.gender, n.created_at as member_since,
    (select min(b.person_id) from {{ ref('bridge_person_phone') }} b
      where b.is_valid and b.phone_norm in (n.phone_norm, n.phone2_norm)) as person_id
from {{ ref('stg_network') }} n
left join {{ ref('dim_grade') }} g on g.grade_id = n.grade_id
left join {{ ref('dim_grade') }} ga on ga.grade_id = n.grade_at_start
left join {{ ref('dim_grade') }} el on el.grade_id = n.eligible_grade
left join {{ ref('stg_network') }} sp on sp.user_id = n.sponsor_id
)
select base.*,
    case
        when base.person_id is null then null
        when list_bool_or(list_transform(string_split(concat_ws(' | ', d.name, d.aliases), ' | '),
                 lambda x: {{ names_compatible(name_tokens('base.name'), name_tokens('x')) }})) then 'name_match'
        else 'same_number'
    end as link_kind
from base left join {{ ref('dim_person') }} d using (person_id)
