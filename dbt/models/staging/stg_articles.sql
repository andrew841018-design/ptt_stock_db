{{ config(materialized='view') }}

-- staging：跨 adapter 型別投射 + 欄位命名統一
SELECT
    CAST(article_id   AS {{ dbt.type_int() }})       AS article_id,
    CAST(source_id    AS {{ dbt.type_int() }})       AS source_id,
    CAST(url          AS {{ dbt.type_string() }})    AS url,
    CAST(title        AS {{ dbt.type_string() }})    AS title,
    CAST(author       AS {{ dbt.type_string() }})    AS author_hash,
    CAST(content      AS {{ dbt.type_string() }})    AS content,
    CAST(push_count   AS {{ dbt.type_int() }})       AS push_count,
    CAST(published_at AS {{ dbt.type_timestamp() }}) AS published_at,
    CAST(scraped_at   AS {{ dbt.type_timestamp() }}) AS scraped_at
FROM {{ source('ptt', 'articles') }}
