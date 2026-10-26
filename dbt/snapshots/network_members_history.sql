{% snapshot network_members_history %}
{{
    config(
        target_schema='snapshots',
        unique_key='user_id',
        strategy='check',
        check_cols=[
            'grade_id', 'is_active', 'direct_count', 'depth', 'personal_referrals',
            'grade_at_start', 'eligible_grade', 'is_promoted', 'sponsor_id',
            'personal_sales_ttc', 'personal_sales_ht', 'personal_sales_net',
            'pending_personal_sales_ttc', 'pending_personal_sales_ht', 'pending_personal_sales_net',
            'team_sales_ttc', 'team_sales_ht', 'team_sales_net',
            'pending_team_sales_ttc', 'pending_team_sales_ht', 'pending_team_sales_net',
            'downline_sales_ttc', 'downline_sales_ht', 'downline_sales_net',
            'pending_downline_sales_ttc', 'pending_downline_sales_ht', 'pending_downline_sales_net',
            'parainage_sales_ttc', 'parainage_sales_ht', 'parainage_sales_net',
            'pending_parainage_sales_ttc', 'pending_parainage_sales_ht', 'pending_parainage_sales_net',
        ],
    )
}}
-- One row per distinct state a network member has ever had (an SCD-2 table dbt manages: each
-- column above that changes cuts a new row with dbt_valid_from/dbt_valid_to; unlisted columns
-- below, like name or phone, are carried along but don't by themselves trigger a new row).
-- A new row is cut only on a real change in the "progress" dimension -- grade, activity, hierarchy
-- position, or sales -- not on every nightly run, so this stays compact.
select
    user_id, name, phone_norm, phone2_norm, grade, grade_id, boutique_code, numero_membre,
    is_active, direct_count, depth, personal_referrals, grade_at_start, eligible_grade,
    is_promoted, sponsor_id,
    personal_sales_ttc, personal_sales_ht, personal_sales_net,
    pending_personal_sales_ttc, pending_personal_sales_ht, pending_personal_sales_net,
    team_sales_ttc, team_sales_ht, team_sales_net,
    pending_team_sales_ttc, pending_team_sales_ht, pending_team_sales_net,
    downline_sales_ttc, downline_sales_ht, downline_sales_net,
    pending_downline_sales_ttc, pending_downline_sales_ht, pending_downline_sales_net,
    parainage_sales_ttc, parainage_sales_ht, parainage_sales_net,
    pending_parainage_sales_ttc, pending_parainage_sales_ht, pending_parainage_sales_net
from {{ ref('stg_network') }}
{% endsnapshot %}
