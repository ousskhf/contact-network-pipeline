-- Every normalised number found in staging must exist in the bridge (replaces check_integrity*.py).
select distinct phone_norm from {{ ref('stg_contact_phones') }}
except
select phone_norm from {{ ref('bridge_person_phone') }}
