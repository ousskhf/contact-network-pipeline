-- The grade ladder as the source system publishes it. next_objective is the published objective of the
-- next grade up (null where the source system publishes 0 / no next grade). The source system does not say which
-- sales figure an objective is measured against, so no progress percentage is baked in here.
select
    id as grade_id,
    name as grade,
    sort_order,
    nullif(objective, 0) as objective,
    min_vente_perso,
    director_min_ca,
    required_confirmed_directors,
    lead(name) over w as next_grade,
    nullif(lead(objective) over w, 0) as next_objective
from {{ source('raw', 'grades') }}
window w as (order by sort_order)
