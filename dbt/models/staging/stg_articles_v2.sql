{{ config(materialized='view') }}

with raw as (
    select
        raw_id,
        source_name,
        raw_payload,
        ingested_at
    from {{ source('raw_ptt', 'raw_articles') }}
),

extracted as (
    select
        raw_id,
        source_name,
        ingested_at,
        nullif(trim(raw_payload->>'url'), '')          as url,
        nullif(trim(raw_payload->>'title'), '')        as title,
        nullif(trim(raw_payload->>'author'), '')       as author_raw,
        nullif(raw_payload->>'content', '')            as content,
        case
            when raw_payload->>'push_count' ~ '^-?[0-9]+$'
            then (raw_payload->>'push_count')::int
            else null
        end                                            as push_count,
        {{ parse_date_multi_format("raw_payload->>'published_at'", "source_name") }} as published_at,
        {{ parse_date_multi_format("raw_payload->>'scraped_at'",   "source_name") }} as scraped_at_raw
    from raw
),

ranked as (
    select
        *,
        row_number() over (
            partition by url
            order by ingested_at desc, raw_id desc
        ) as rn,
        min(raw_id) over (partition by url) as canonical_article_id
    from extracted
    where url is not null
)

select
    cast(canonical_article_id                                                                  as {{ dbt.type_int() }})       as article_id,
    cast(url                                                                                   as {{ dbt.type_string() }})    as url,
    cast(source_name                                                                           as {{ dbt.type_string() }})    as source_name,
    cast(title                                                                                 as {{ dbt.type_string() }})    as title,
    cast({{ pii_hash('author_raw') }}                                                          as {{ dbt.type_string() }})    as author_hash,
    cast(content                                                                               as {{ dbt.type_string() }})    as content,
    cast(push_count                                                                            as {{ dbt.type_int() }})       as push_count,
    cast(published_at                                                                          as {{ dbt.type_timestamp() }}) as published_at,
    cast(coalesce(scraped_at_raw, ingested_at)                                                 as {{ dbt.type_timestamp() }}) as scraped_at,
    cast(ingested_at                                                                           as {{ dbt.type_timestamp() }}) as ingest_time,
    cast('raw_articles'                                                                        as {{ dbt.type_string() }})    as source_system,
    cast(current_timestamp                                                                     as {{ dbt.type_timestamp() }}) as staging_processed_at
from ranked
where rn = 1
