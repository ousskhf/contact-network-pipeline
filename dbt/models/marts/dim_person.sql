with members as (
    select p.person_id, c.source_row, c.name
    from {{ ref('int_contact_person') }} p
    join {{ ref('stg_contacts') }} c using (source_row)
),
names as (
    select person_id, name, min(source_row) as first_row
    from members where name <> '' group by person_id, name
)
select
    m.person_id,
    coalesce(max(n.name) filter (where n.first_row = f.first_row), '') as name,
    nullif(string_agg(distinct n.name, ' | ') filter (where n.first_row > f.first_row), '') as aliases,
    count(distinct m.source_row) as n_source_rows,
    (select count(*) from {{ ref('bridge_person_phone') }} b where b.person_id = m.person_id) as n_phones
from members m
left join names n using (person_id)
left join (select person_id, min(first_row) as first_row from names group by person_id) f using (person_id)
group by m.person_id
