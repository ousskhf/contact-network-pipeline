-- A merged person must be linked by at least one valid number shared by two rows.
select m.person_id from {{ ref('merge_audit') }} m
where not exists (
    select 1
    from {{ ref('stg_contact_phones') }} s
    join {{ ref('int_contact_person') }} p using (source_row)
    where p.person_id = m.person_id and s.is_valid
    group by s.phone_norm
    having count(distinct s.source_row) > 1
)
