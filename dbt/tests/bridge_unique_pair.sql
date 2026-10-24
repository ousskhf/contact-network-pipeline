select person_id, phone_norm, count(*) from {{ ref('bridge_person_phone') }}
group by 1, 2 having count(*) > 1
