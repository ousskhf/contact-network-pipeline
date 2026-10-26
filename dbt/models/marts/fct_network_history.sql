-- Friendly read of the network_members_history snapshot: one row per distinct state a member has
-- ever had, grade name resolved at that point in time, dbt's SCD columns renamed to match the
-- rest of the marts' French naming.
select
    h.user_id,
    h.name,
    h.phone_norm,
    h.phone2_norm,
    coalesce(g.grade, h.grade) as grade,
    h.is_active,
    h.direct_count,
    h.depth,
    h.sponsor_id,
    h.personal_sales_ttc, h.personal_sales_ht, h.personal_sales_net,
    h.pending_personal_sales_ttc, h.pending_personal_sales_ht, h.pending_personal_sales_net,
    h.team_sales_ttc, h.team_sales_ht, h.team_sales_net,
    h.pending_team_sales_ttc, h.pending_team_sales_ht, h.pending_team_sales_net,
    h.downline_sales_ttc, h.downline_sales_ht, h.downline_sales_net,
    h.pending_downline_sales_ttc, h.pending_downline_sales_ht, h.pending_downline_sales_net,
    h.parainage_sales_ttc, h.parainage_sales_ht, h.parainage_sales_net,
    h.pending_parainage_sales_ttc, h.pending_parainage_sales_ht, h.pending_parainage_sales_net,
    h.dbt_valid_from as valide_du,
    h.dbt_valid_to as valide_au
from {{ ref('network_members_history') }} h
left join {{ ref('dim_grade') }} g on g.grade_id = h.grade_id
