{{ config(materialized='view') }}

with raw as (
    select
        raw_id,
        article_id_raw,
        raw_payload,
        ingested_at
    from {{ source('raw_ptt', 'raw_sentiment_scores') }}
),

extracted as (
    select
        raw_id,
        article_id_raw,
        ingested_at,
        case
            when raw_payload->>'score' ~ '^-?[0-9]+(\.[0-9]+)?$'
            then (raw_payload->>'score')::float
            else null
        end                                              as score,
        case
            when raw_payload->>'calculated_at' is null then null
            when raw_payload->>'calculated_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}'
                then (raw_payload->>'calculated_at')::timestamp
            else null
        end                                              as calculated_at
    from raw
),

deduped as (
    select
        *,
        row_number() over (
            partition by article_id_raw
            order by ingested_at desc, raw_id desc
        ) as rn
    from extracted
    where article_id_raw is not null
)

select
    cast(encode(digest(article_id_raw, 'sha256'), 'hex') as {{ dbt.type_string() }})  as score_id,
    cast(article_id_raw                                  as {{ dbt.type_string() }})  as article_id_raw,
    cast(score                                           as {{ dbt.type_float() }})   as score,
    cast(calculated_at                                   as {{ dbt.type_timestamp() }}) as calculated_at,
    cast(ingested_at                                     as {{ dbt.type_timestamp() }}) as ingest_time,
    cast('raw_sentiment_scores'                          as {{ dbt.type_string() }})  as source_system,
    cast(current_timestamp                               as {{ dbt.type_timestamp() }}) as staging_processed_at
from deduped
where rn = 1
