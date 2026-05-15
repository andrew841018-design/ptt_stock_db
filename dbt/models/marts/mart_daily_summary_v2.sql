{{ config(materialized='table') }}

select
    fact_date,
    source_name,
    article_count,
    pos_count,
    neg_count,
    neu_count,
    avg_score,
    cast(pos_count as {{ dbt.type_float() }}) / nullif(article_count, 0) as pos_ratio,
    cast(neg_count as {{ dbt.type_float() }}) / nullif(article_count, 0) as neg_ratio,
    pipeline_version
from {{ ref('fact_sentiment_v2') }}
order by fact_date desc, article_count desc
