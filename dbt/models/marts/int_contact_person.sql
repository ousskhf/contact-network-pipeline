-- Connected components: contact rows sharing a normalised number are one person.
-- Min-label propagation over the "shares a phone" graph.
{{ config(materialized='table') }}
with recursive edges as (
    select distinct a.source_row as a, b.source_row as b
    from {{ ref('stg_contact_phones') }} a
    join {{ ref('stg_contact_phones') }} b
      on a.phone_norm = b.phone_norm and a.source_row <> b.source_row
     and a.is_valid and b.is_valid
),
walk(node, label) as (
    select source_row, source_row from {{ ref('stg_contacts') }}
    union
    select e.b, w.label from walk w join edges e on e.a = w.node
)
select node as source_row, min(label) as person_id
from walk
group by node
