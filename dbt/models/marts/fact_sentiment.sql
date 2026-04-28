{{ config(materialized='table') }}

-- 事實表：每 (fact_date × source_id) 的情緒統計
-- 注意：COUNT FILTER 是 PG/Snowflake 語法；BQ 用 COUNTIF
-- 用 {{ dbt_utils }} 不夠抽象，這裡手動 dispatch
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
