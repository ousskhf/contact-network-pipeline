-- A phone number is a channel, not a person: members hand their number to the people under them for deliveries.
-- One row per valid number, with how many distinct contact people and network members use it.
with contact_use as (
    select b.phone_norm, b.person_id
    from {{ ref('bridge_person_phone') }} b
    where b.is_valid
),
member_use as (
    select user_id, phone_norm from {{ ref('stg_network') }}
    where regexp_matches(phone_norm, '^\+?[0-9]{6,15}$')
    union
    select user_id, phone2_norm from {{ ref('stg_network') }}
    where regexp_matches(phone2_norm, '^\+?[0-9]{6,15}$')
),
numbers as (
    select phone_norm from contact_use union select phone_norm from member_use
)
select
    n.phone_norm,
    (select count(distinct person_id) from contact_use c where c.phone_norm = n.phone_norm) as n_contact_people,
    (select count(distinct user_id) from member_use m where m.phone_norm = n.phone_norm) as n_members,
    (select count(distinct person_id) from contact_use c where c.phone_norm = n.phone_norm) > 1
      or (select count(distinct user_id) from member_use m where m.phone_norm = n.phone_norm) > 1 as is_shared
from numbers n
