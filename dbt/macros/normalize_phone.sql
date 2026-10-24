{# Tunisian numbers: drop separators and a leading +216/00216. Other country codes are left untouched. #}
{% macro normalize_phone(col) %}
nullif(
  regexp_replace(
    regexp_replace(regexp_replace(trim({{ col }}), '[\s\-\.\(\)]', '', 'g'), '^\+216', ''),
    '^00216', ''),
  '')
{% endmacro %}
