-- Phase 2: the tables that record what the loader did and what it refused.

-- One row per file loaded: how many rows came in, went through, and were rejected.
CREATE TABLE IF NOT EXISTS audit.load_log (
    log_id         bigserial PRIMARY KEY,
    batch_id       text      NOT NULL,
    source_file    text      NOT NULL,
    rows_read      integer   NOT NULL DEFAULT 0,
    rows_loaded    integer   NOT NULL DEFAULT 0,
    rows_rejected  integer   NOT NULL DEFAULT 0,
    seconds_taken  numeric(10,3),
    logged_at      timestamp NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_load_log_batch ON audit.load_log (batch_id);

-- Rows that failed a check. Never silently dropped: kept here with the reason.
CREATE TABLE IF NOT EXISTS quarantine.rejected_rows (
    rejected_id  bigserial PRIMARY KEY,
    batch_id     text      NOT NULL,
    table_name   text      NOT NULL,
    row_as_text  text      NOT NULL,
    reason       text      NOT NULL,
    rejected_at  timestamp NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_quarantine_batch  ON quarantine.rejected_rows (batch_id);
CREATE INDEX IF NOT EXISTS ix_quarantine_reason ON quarantine.rejected_rows (reason);