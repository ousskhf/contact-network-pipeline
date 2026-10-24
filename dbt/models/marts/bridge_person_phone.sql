-- One row per (person, number): no cap on numbers per person. Invalid entries are kept, flagged.
select distinct p.person_id, ph.phone_norm, ph.is_valid
from {{ ref('stg_contact_phones') }} ph
join {{ ref('int_contact_person') }} p using (source_row)
