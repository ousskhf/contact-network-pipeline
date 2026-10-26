-- Every member must have exactly one "current" row (valide_au is null) in the history --
-- otherwise a change was recorded without closing out the previous state.
select user_id, count(*) as n_current
from {{ ref('fct_network_history') }}
where valide_au is null
group by user_id
having count(*) <> 1
