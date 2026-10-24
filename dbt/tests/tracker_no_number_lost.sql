-- Every phone entry (valid or not) must appear in the exported tracker.
select distinct s.phone_norm
from {{ ref('stg_contact_phones') }} s
where not exists (
    select 1 from {{ ref('tracker_export') }} t
    where position(s.phone_norm in concat_ws(' ; ', t."Téléphone", t."Téléphone 2", t."Téléphone 3", t."Autres numéros")) > 0
)
