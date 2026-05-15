{{ config(materialized='table') }}

{% if var('use_v2_pipeline', false) %}

SELECT
    fact_date,
    source_id,
    source_name,
    article_count,
    pos_count,
    neg_count,
    neu_count,
    avg_score
FROM {{ ref('fact_sentiment_v2') }}

{% else %}

WITH joined AS (
    SELECT
        CAST({{ dbt.date_trunc('day', 'a.scraped_at') }} AS DATE) AS fact_date,
        a.source_id,
        s.source_name,
        ss.score
    FROM {{ ref('stg_articles') }} a
    JOIN {{ ref('stg_sentiment_scores') }} ss ON ss.article_id = a.article_id
    JOIN {{ ref('stg_sources') }} s           ON s.source_id   = a.source_id
)
SELECT
    fact_date,
    source_id,
    source_name,
    COUNT(*)                                                      AS article_count,
    {{ count_if('score > 0.2') }}                                 AS pos_count,
    {{ count_if('score < -0.2') }}                                AS neg_count,
    {{ count_if('score BETWEEN -0.2 AND 0.2') }}                  AS neu_count,
    AVG(score)                                                    AS avg_score
FROM joined
GROUP BY fact_date, source_id, source_name

{% endif %}
