{#
  By default dbt names schemas like "staging_marts". This override uses the schema
  name exactly as written in dbt_project.yml, so models land in staging and marts.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}