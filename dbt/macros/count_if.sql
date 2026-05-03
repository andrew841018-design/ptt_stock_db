{# 跨 adapter 的 conditional count：PG 用 FILTER；BQ 用 COUNTIF #}
{% macro count_if(condition) %}
    {{ adapter.dispatch('count_if', 'ptt_sentiment') (condition) }}
{% endmacro %}

{% macro default__count_if(condition) %}
    COUNT(*) FILTER (WHERE {{ condition }})
{% endmacro %}

{% macro postgres__count_if(condition) %}
    COUNT(*) FILTER (WHERE {{ condition }})
{% endmacro %}

{% macro bigquery__count_if(condition) %}
    COUNTIF({{ condition }})
{% endmacro %}
