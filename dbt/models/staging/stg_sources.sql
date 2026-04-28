{{ config(materialized='view') }}

SELECT
    CAST(source_id   AS {{ dbt.type_int() }})    AS source_id,
    CAST(source_name AS {{ dbt.type_string() }}) AS source_name,
    CAST(url         AS {{ dbt.type_string() }}) AS source_url
FROM {{ source('ptt', 'sources') }}
