-- Phase 2: create the five schemas.
-- raw        data exactly as it arrives, plus batch_id and loaded_at
-- staging    cleaned copies of raw (built by dbt)
-- marts      the star schema the dashboard reads (built by dbt)
-- quarantine rows that failed checks, with the reason
-- audit      load logs and test results

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS quarantine;
CREATE SCHEMA IF NOT EXISTS audit;