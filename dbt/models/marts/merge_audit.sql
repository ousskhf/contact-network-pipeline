-- Which contact rows were fused into which person (replaces merge_log.csv).
select
    p.person_id,
    count(*) as n_rows,
    string_agg(cast(p.source_row as varchar), ';' order by p.source_row) as source_rows,
    string_agg(c.name, ' | ' order by p.source_row) as names
from {{ ref('int_contact_person') }} p
join {{ ref('stg_contacts') }} c using (source_row)
group by p.person_id
having count(*) > 1
