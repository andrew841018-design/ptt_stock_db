{{ config(materialized='view') }}

with raw as (
    select
        raw_id,
        source_name,
        raw_payload,
        ingested_at
    from {{ source('raw_ptt', 'raw_sources') }}
),

extracted as (
    select
        raw_id,
        ingested_at,
        nullif(trim(lower(source_name)), '')      as source_name,
        nullif(trim(raw_payload->>'url'), '')     as source_url
    from raw
),

ranked as (
    select
        *,
        row_number() over (
            partition by source_name
            order by ingested_at desc, raw_id desc
        ) as rn,
        min(raw_id) over (partition by source_name) as canonical_source_id
    from extracted
    where source_name is not null
)

select
    cast(canonical_source_id                          as {{ dbt.type_int() }})       as source_id,
    cast(source_name                                  as {{ dbt.type_string() }})    as source_name,
    cast(source_url                                   as {{ dbt.type_string() }})    as source_url,
    cast(ingested_at                                  as {{ dbt.type_timestamp() }}) as ingest_time,
    cast('raw_sources'                                as {{ dbt.type_string() }})    as source_system,
    cast(current_timestamp                            as {{ dbt.type_timestamp() }}) as staging_processed_at
from ranked
where rn = 1
