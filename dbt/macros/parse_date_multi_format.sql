{#
  parse_date_multi_format(date_expr, source_name_expr)

  Per-source date string -> TIMESTAMPTZ in UTC. Scrapers MUST NOT normalize before
  writing raw_* (EL+T principle); macro absorbs per-source format dispatch here.

  Format dispatch (by source_name):
    - ptt                                      Taiwan local 'YYYY-MM-DD HH:MM:SS'
    - cnn, wsj, marketwatch, wayback_cnn,
      wayback_wsj                              RFC 2822 'Dy, DD Mon YYYY HH:MM:SS TZ'
    - reddit                                   Unix epoch seconds (digits only)
    - cnyes, yfinance, default ISO consumers   ISO 8601 'YYYY-MM-DD[T ]HH:MM:SS[...]'

  Returns: timestamp with time zone (UTC). NULL on:
    - NULL or empty input
    - format dispatch missed
    - regex pre-check failed

  Postgres-specific. Default dispatch mirrors postgres for BQ readiness;
  BQ adapter override deferred to Phase 3 if dbt-bigquery is enabled.
#}

{% macro parse_date_multi_format(date_expr, source_name_expr) %}
    {{ adapter.dispatch('parse_date_multi_format', 'ptt_sentiment') (date_expr, source_name_expr) }}
{% endmacro %}

{% macro default__parse_date_multi_format(date_expr, source_name_expr) %}
    {{ ptt_sentiment.postgres__parse_date_multi_format(date_expr, source_name_expr) }}
{% endmacro %}

{% macro postgres__parse_date_multi_format(date_expr, source_name_expr) %}
    case
        when ({{ date_expr }}) is null or trim({{ date_expr }}) = '' then null

        when ({{ source_name_expr }}) = 'ptt'
             and ({{ date_expr }}) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}'
             then ((substring({{ date_expr }} from 1 for 19))::timestamp at time zone 'Asia/Taipei') at time zone 'UTC'

        when ({{ source_name_expr }}) = 'reddit'
             and ({{ date_expr }}) ~ '^[0-9]+(\.[0-9]+)?$'
             then to_timestamp(({{ date_expr }})::double precision)

        when ({{ source_name_expr }}) in ('cnn', 'wsj', 'marketwatch', 'wayback_cnn', 'wayback_wsj')
             and ({{ date_expr }}) ~ '^[A-Za-z]{3},\s+[0-9]{1,2}\s+[A-Za-z]{3}\s+[0-9]{4}\s+[0-9]{2}:[0-9]{2}:[0-9]{2}'
             then (to_timestamp(
                       substring({{ date_expr }} from '^[A-Za-z]{3},\s+[0-9]{1,2}\s+[A-Za-z]{3}\s+[0-9]{4}\s+[0-9]{2}:[0-9]{2}:[0-9]{2}'),
                       'Dy, DD Mon YYYY HH24:MI:SS'
                   ) at time zone 'UTC')

        when ({{ date_expr }}) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9]{2}:[0-9]{2}:[0-9]{2})?'
             then ((substring({{ date_expr }} from '^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9]{2}:[0-9]{2}:[0-9]{2})?'))::timestamp at time zone 'UTC')

        else null
    end
{% endmacro %}
