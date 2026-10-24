-- One row per (contact row, phone slot). Unpivots every "Phone N - Value" column,
-- so there is no limit on how many numbers a contact can have.
select
    source_row,
    phone_slot,
    phone_raw,
    {{ normalize_phone('phone_raw') }} as phone_norm,
    -- short codes, letters etc. are kept but never used to merge people
    regexp_matches(phone_norm, '^\+?[0-9]{6,15}$') as is_valid
from (
    unpivot {{ source('raw', 'contacts') }}
    on columns('^Phone \d+ - Value$')
    into name phone_slot value phone_raw
)
where {{ normalize_phone('phone_raw') }} is not null
