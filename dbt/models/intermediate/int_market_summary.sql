{{ config(materialized='view') }}

with articles as (
    select * from {{ ref('int_articles_with_sentiment') }}
),

sources as (
    select
        source_id,
        source_name,
        source_url
    from {{ ref('stg_sources_v2') }}
)

select
    a.article_id,
    a.url,
    a.source_name,
    s.source_id,
    s.source_url,
    {{ market_for_source('a.source_name') }} as market_code,
    a.title,
    a.author_hash,
    a.push_count,
    a.published_at,
    a.scraped_at,
    a.sentiment_score,
    a.sentiment_score_calculated_at,
    a.ingest_time
from articles a
left join sources s
    on s.source_name = a.source_name
