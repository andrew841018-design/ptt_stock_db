{#
  market_for_source(source_name_expr)

  Hardcoded mapping of source_name -> market_code (US / TW), kept in sync with
  dependent_code/config.py:SOURCE_META (single source of truth for Python).

  TW: ptt, cnyes
  US: reddit, cnn, wsj, marketwatch, wayback_cnn, wayback_wsj

  Returns NULL for unknown source (surfaces via accepted_values test on
  int_market_summary.market_code).
#}

{% macro market_for_source(source_name_expr) %}
    case ({{ source_name_expr }})
        when 'ptt'         then 'TW'
        when 'cnyes'       then 'TW'
        when 'reddit'      then 'US'
        when 'cnn'         then 'US'
        when 'wsj'         then 'US'
        when 'marketwatch' then 'US'
        when 'wayback_cnn' then 'US'
        when 'wayback_wsj' then 'US'
        else null
    end
{% endmacro %}
