-- Merged contact people to look at: pairs of rows that were fused through a shared number but carry names that
-- do not match (different people on one number, or the same person spelled differently).
with named as (
    select m.person_id, p.source_row, c.name, {{ name_tokens('c.name') }} as tokens
    from {{ ref('merge_audit') }} m
    join {{ ref('int_contact_person') }} p using (person_id)
    join {{ ref('stg_contacts') }} c using (source_row)
),
conflicts as (
    select a.person_id, count(*) as n_name_conflicts
    from named a join named b on a.person_id = b.person_id and a.source_row < b.source_row
    where not {{ names_compatible('a.tokens', 'b.tokens') }}
    group by a.person_id
)
select m.person_id, m.n_rows, m.source_rows, m.names,
       coalesce(c.n_name_conflicts, 0) as n_name_conflicts,
       coalesce(c.n_name_conflicts, 0) > 0 as names_conflict
from {{ ref('merge_audit') }} m
left join conflicts c using (person_id)
