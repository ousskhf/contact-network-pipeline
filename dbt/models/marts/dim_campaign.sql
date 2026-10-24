select
    id as campaign_id,
    name,
    try_cast(left(start_date, 10) as date) as start_date,
    try_cast(left(end_date, 10) as date) as end_date,
    is_active,
    is_finalized
from {{ source('raw', 'campaign') }}
