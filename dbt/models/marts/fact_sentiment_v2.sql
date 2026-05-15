{{ config(materialized='table') }}

with joined as (
    select
        cast({{ dbt.date_trunc('day', 'a.scraped_at') }} as date) as fact_date,
        s.source_id,
        a.source_name,
        a.sentiment_score as score
    from {{ ref('int_articles_with_sentiment') }} a
    left join {{ ref('stg_sources_v2') }} s
        on s.source_name = a.source_name
    where a.sentiment_score is not null
)

select
    fact_date,
    source_id,
    source_name,
    count(*)                                       as article_count,
    {{ count_if('score > 0.2') }}                  as pos_count,
    {{ count_if('score < -0.2') }}                 as neg_count,
    {{ count_if('score between -0.2 and 0.2') }}   as neu_count,
    avg(score)                                     as avg_score,
    cast('v2' as {{ dbt.type_string() }})          as pipeline_version
from joined
group by fact_date, source_id, source_name
