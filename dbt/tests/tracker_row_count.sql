-- One tracker row per person, plus one per network member not matched to a contact.
select 1 from (
    select (select count(*) from {{ ref('tracker_export') }}) as got,
           (select count(*) from {{ ref('dim_person') }})
         + (select count(*) from {{ ref('fct_network_membership') }} where person_id is null) as want
) where got <> want
