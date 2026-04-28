{{ config(materialized='table') }}

-- Data Mart：直接供 API / 儀表板查詢的預聚合表
-- 粒度：(fact_date × source_id)
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
