{# 
  pii_hash — PII author hash macro (faithful port of dependent_code/pii_masking.py:hash_author)
  
  Python original:
    salted = f"{PII_HASH_SALT}:{author}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()[:16]
  
  SQL port (Postgres pgcrypto):
    substring(encode(digest(salt || ':' || author, 'sha256'), 'hex') from 1 for 16)
  
  Requires `CREATE EXTENSION pgcrypto;` (DDL handles this).
  Returns NULL when input is NULL (digest() rejects NULL bytes, so guard).
#}
{% macro pii_hash(column_expr) %}
    {{ adapter.dispatch('pii_hash', 'ptt_sentiment') (column_expr) }}
{% endmacro %}

{% macro default__pii_hash(column_expr) %}
    {%- set salt = env_var("PII_HASH_SALT", "change-me-in-production") -%}
    case
      when ({{ column_expr }}) is null then null
      else substring(
        encode(
          digest('{{ salt }}' || ':' || ({{ column_expr }}), 'sha256'),
          'hex'
        )
        from 1 for 16
      )
    end
{% endmacro %}

{% macro postgres__pii_hash(column_expr) %}
    {%- set salt = env_var("PII_HASH_SALT", "change-me-in-production") -%}
    case
      when ({{ column_expr }}) is null then null
      else substring(
        encode(
          digest('{{ salt }}' || ':' || ({{ column_expr }}), 'sha256'),
          'hex'
        )
        from 1 for 16
      )
    end
{% endmacro %}

{% macro bigquery__pii_hash(column_expr) %}
    {%- set salt = env_var("PII_HASH_SALT", "change-me-in-production") -%}
    case
      when ({{ column_expr }}) is null then null
      else substr(
        to_hex(sha256(concat('{{ salt }}', ':', ({{ column_expr }})))),
        1, 16
      )
    end
{% endmacro %}
