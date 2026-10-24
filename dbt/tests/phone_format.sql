{{ config(severity='warn') }}
-- Entries that are not a plausible phone number (short codes, letters...). Kept but flagged; review them.
select phone_norm from {{ ref('stg_contact_phones') }}
where not is_valid
