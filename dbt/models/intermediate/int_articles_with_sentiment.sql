{{ config(materialized='view') }}

with articles as (
    select * from {{ ref('stg_articles_v2') }}
),

scores as (
    select
        article_id_raw,
        score,
        calculated_at
    from {{ ref('stg_sentiment_scores_v2') }}
)

select
    a.article_id,
    a.url,
    a.source_name,
    a.title,
    a.author_hash,
    a.content,
    a.push_count,
    a.published_at,
    a.scraped_at,
    a.ingest_time,
    s.score          as sentiment_score,
    s.calculated_at  as sentiment_score_calculated_at
from articles a
left join scores s
    on s.article_id_raw = a.url
