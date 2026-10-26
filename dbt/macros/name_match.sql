{# Names as comparable token lists: lower case, no accents, letters and digits only, one-letter bits dropped. #}
{% macro name_tokens(col) %}
list_distinct(list_filter(
    string_split(trim(regexp_replace(lower(strip_accents(coalesce({{ col }}, ''))), '[^\pL\pN]+', ' ', 'g')), ' '),
    lambda t: length(t) >= 2))
{% endmacro %}

{# Two token lists are the same person when either is empty (nothing to compare) or they share two tokens,
   or the only token of the shorter one. One shared surname ("Test") is a family, not a match. #}
{% macro names_compatible(a, b) %}
(len({{ a }}) = 0 or len({{ b }}) = 0
 or len(list_intersect({{ a }}, {{ b }})) >= least(2, len({{ a }}), len({{ b }})))
{% endmacro %}
