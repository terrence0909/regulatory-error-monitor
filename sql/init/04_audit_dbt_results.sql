-- Phase 6: where dbt test results are kept.
-- Safe to run many times (IF NOT EXISTS). The recorder script runs this file itself,
-- so an existing database gets the tables without being rebuilt.

-- One row per dbt run (for example one "dbt build").
CREATE TABLE IF NOT EXISTS audit.dbt_runs (
    run_id            text      PRIMARY KEY,
    command           text      NOT NULL,
    started_at        timestamp,
    elapsed_seconds   numeric(10,3),
    tests_total       integer   NOT NULL DEFAULT 0,
    tests_passed      integer   NOT NULL DEFAULT 0,
    tests_warned      integer   NOT NULL DEFAULT 0,
    tests_failed      integer   NOT NULL DEFAULT 0,
    tests_skipped     integer   NOT NULL DEFAULT 0,
    models_succeeded  integer   NOT NULL DEFAULT 0,
    models_failed     integer   NOT NULL DEFAULT 0,
    recorded_at       timestamp NOT NULL DEFAULT now()
);

-- One row per test in each run.
CREATE TABLE IF NOT EXISTS audit.test_results (
    result_id      bigserial PRIMARY KEY,
    run_id         text      NOT NULL REFERENCES audit.dbt_runs (run_id) ON DELETE CASCADE,
    test_name      text      NOT NULL,
    test_kind      text      NOT NULL,   -- generic (from a yml file) or singular (a .sql file)
    model_name     text,
    column_name    text,
    severity       text      NOT NULL,   -- error stops the pipeline, warn only reports
    status         text      NOT NULL,   -- pass, warn, fail, error or skipped
    failing_rows   integer,
    seconds_taken  numeric(10,3),
    message        text
);
CREATE INDEX IF NOT EXISTS ix_test_results_run    ON audit.test_results (run_id);
CREATE INDEX IF NOT EXISTS ix_test_results_status ON audit.test_results (status);