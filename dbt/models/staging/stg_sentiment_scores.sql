{{ config(materialized='view') }}

SELECT
    CAST(score_id      AS {{ dbt.type_int() }})       AS score_id,
    CAST(article_id    AS {{ dbt.type_int() }})       AS article_id,
    CAST(score         AS {{ dbt.type_float() }})     AS score,
    CAST(calculated_at AS {{ dbt.type_timestamp() }}) AS calculated_at
FROM {{ source('ptt', 'sentiment_scores') }}
