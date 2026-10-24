-- Phone exports often keep the whole address as free text in the street field ("Tunis, Tunisia"), so a
-- trailing ", Tunisia" / "/Egypt" there is read as the country; a street that is only a country name is empty.
with raw as (
    select
        source_row,
        trim(concat_ws(' ', "First Name", "Last Name")) as name,
        nullif(trim("Address 1 - City"), '') as city,
        nullif(trim("Address 1 - Region"), '') as region,
        nullif(trim("Address 1 - Street"), '') as street,
        nullif(trim("Address 1 - Country"), '') as country,
        nullif(trim("Organization Name"), '') as org_name,
        nullif(trim("Organization Title"), '') as org_title
    from {{ source('raw', 'contacts') }}
),
street_country as (
    select *, regexp_extract(street, '(?i)(?:^|[,/])\s*(tunisia|tunisie|egypt|egypte|égypte)\s*$', 1) as street_country
    from raw
)
select
    source_row, name, city, region,
    nullif(trim(regexp_replace(street, '(?i)(?:^|\s*[,/])\s*(tunisia|tunisie|egypt|egypte|égypte)\s*$', '')), '') as street,
    {{ normalize_country("coalesce(country, nullif(street_country, ''))") }} as country,
    org_name, org_title
from street_country
