-- Network members, linked to a contact person when either number matches (valid numbers only).
select
    n.member_row, n.name, n.user_id, n.sponsor_id,
    coalesce(g.grade, n.grade) as grade,
    n.is_active, n.boutique_code, n.numero_membre,
    n.personal_sales_ttc, n.team_sales_ttc,
    n.pending_personal_sales_ttc, n.pending_team_sales_ttc,
    n.downline_sales_ttc, n.pending_downline_sales_ttc,
    n.birth_date, n.depth, n.direct_count, n.personal_referrals,
    ga.grade as grade_at_start_name,
    n.is_promoted,
    el.grade as eligible_grade,
    g.sort_order as grade_order, g.next_grade, g.next_objective,
    (select min(b.person_id) from {{ ref('bridge_person_phone') }} b
      where b.is_valid and b.phone_norm in (n.phone_norm, n.phone2_norm)) as person_id
from {{ ref('stg_network') }} n
left join {{ ref('dim_grade') }} g on g.grade_id = n.grade_id
left join {{ ref('dim_grade') }} ga on ga.grade_id = n.grade_at_start
left join {{ ref('dim_grade') }} el on el.grade_id = n.eligible_grade
