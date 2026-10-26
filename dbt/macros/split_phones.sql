{# Two Tunisian numbers typed in one field ("a / b", "a-b", or 16 digits run together): the list of
   normalised numbers. Splits only when every part is a plain 8-digit number; anything else stays one entry. #}
{% macro split_phones(col) %}
(case
  when regexp_matches(regexp_replace(coalesce({{ col }}, ''), '\D', '', 'g'), '^[0-9]{16}$')
    then [left(regexp_replace({{ col }}, '\D', '', 'g'), 8), right(regexp_replace({{ col }}, '\D', '', 'g'), 8)]
  when len(regexp_split_to_array(trim({{ col }}), '\s*[/;]\s*|\s*-\s*')) > 1
   and list_bool_and(list_transform(regexp_split_to_array(trim({{ col }}), '\s*[/;]\s*|\s*-\s*'),
                                    lambda t: regexp_matches({{ normalize_phone('t') }}, '^[0-9]{8}$')))
    then list_transform(regexp_split_to_array(trim({{ col }}), '\s*[/;]\s*|\s*-\s*'), lambda t: {{ normalize_phone('t') }})
  else [{{ normalize_phone(col) }}]
end)
{% endmacro %}
