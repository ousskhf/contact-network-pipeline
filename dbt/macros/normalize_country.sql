{# Canonical French name for the countries seen in phone exports; any other name is kept as typed. #}
{% macro normalize_country(expr) %}
    case lower(trim({{ expr }}))
        when 'tunisia' then 'Tunisie' when 'tunisie' then 'Tunisie'
        when 'egypt' then 'Égypte' when 'egypte' then 'Égypte' when 'égypte' then 'Égypte'
        else nullif(trim({{ expr }}), '')
    end
{% endmacro %}
