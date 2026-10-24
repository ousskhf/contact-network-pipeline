-- Every contact row maps to exactly one person.
select s.source_row
from {{ ref('stg_contacts') }} s
left join {{ ref('int_contact_person') }} p using (source_row)
group by s.source_row
having count(p.person_id) <> 1
