{{ config(materialized='table') }}

{% if var('use_v2_pipeline', false) %}

SELECT
    fact_date,
    source_name,
    article_count,
    pos_count,
    neg_count,
    neu_count,
    avg_score,
    pos_ratio,
    neg_ratio
FROM {{ ref('mart_daily_summary_v2') }}
ORDER BY fact_date DESC, article_count DESC

{% else %}

SELECT
    fact_date,
    source_id,
    source_name,
    article_count,
    pos_count,
    neg_count,
    neu_count,
    avg_score,
    CAST(pos_count AS {{ dbt.type_float() }}) / NULLIF(article_count, 0) AS pos_ratio,
    CAST(neg_count AS {{ dbt.type_float() }}) / NULLIF(article_count, 0) AS neg_ratio
FROM {{ ref('fact_sentiment') }}
ORDER BY fact_date DESC, article_count DESC

{% endif %}
