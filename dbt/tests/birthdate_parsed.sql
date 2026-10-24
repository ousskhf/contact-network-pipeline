{{ config(severity='warn') }}
-- A birth date was delivered but could not be read as a date (format change or junk value).
select member_row from {{ ref('stg_network') }} where birth_date_raw is not null and birth_date is null
