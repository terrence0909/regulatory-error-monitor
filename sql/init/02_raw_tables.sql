-- Phase 2: raw tables.
-- Raw tables have NO primary keys on purpose. The same row can legitimately
-- arrive twice (a late or repeated file), and raw must accept it. Duplicates
-- are removed later, in the staging layer. Indexes make lookups fast instead.
-- Every raw table has batch_id and loaded_at, added by the loader.

-- The lookup of error codes. One row per version of an error.
CREATE TABLE IF NOT EXISTS raw.error_detail (
    error_detail_skey   integer,
    error_code          text,
    source_row_id       text,
    error_description   text,
    response            text,
    error_level         text,
    error_type          text,
    active_date         date,
    inactive_date       date,
    created_date        timestamp,
    created_by          text,
    updated_date        timestamp,
    updated_by          text,
    batch_id            text      NOT NULL,
    loaded_at           timestamp NOT NULL DEFAULT now()
);

-- One row per validation error found on a payment line.
CREATE TABLE IF NOT EXISTS raw.transaction_validation (
    transaction_val_skey      bigint,
    error_detail_skey_fk      integer,
    file_skey_fk              integer,
    message_identification    text,
    end_to_end_identification text,
    rule_skey_fk              integer,
    sequence_number           integer,
    sub_sequence              integer,
    line_number               integer,
    entity_code               text,
    entity_name               text,
    reporting_attribute       text,
    reporting_component       text,
    report_reference_number   text,
    report_start_datetime     timestamp,
    reporting_qualifier       text,
    flow                      text,
    original_file_reference   text,
    error_status              text,
    error_number              integer,
    user_id                   text,
    transaction_error_id      text,
    external_ref_number       text,
    transaction_type          text,
    error_type                text,
    error_description         text,
    last_update_date          timestamp,
    processed_date            date,
    processed_date_time       timestamp,
    created_date              timestamp,
    created_by                text,
    updated_date              timestamp,
    updated_by                text,
    transaction_status        text,
    batch_id                  text      NOT NULL,
    loaded_at                 timestamp NOT NULL DEFAULT now()
);

-- The rules that were checked (invented for this project).
CREATE TABLE IF NOT EXISTS raw.validation_rule (
    rule_skey      integer,
    rule_code      text,
    rule_name      text,
    rule_category  text,
    updated_date   timestamp,
    batch_id       text      NOT NULL,
    loaded_at      timestamp NOT NULL DEFAULT now()
);

-- The files that were received (invented for this project).
CREATE TABLE IF NOT EXISTS raw.file_registry (
    file_skey    integer,
    file_name    text,
    received_at  timestamp,
    row_count    integer,
    batch_id     text      NOT NULL,
    loaded_at    timestamp NOT NULL DEFAULT now()
);

-- Indexes: the loader deletes by batch_id, and dbt looks rows up by key.
CREATE INDEX IF NOT EXISTS ix_raw_error_detail_batch   ON raw.error_detail (batch_id);
CREATE INDEX IF NOT EXISTS ix_raw_error_detail_skey    ON raw.error_detail (error_detail_skey);
CREATE INDEX IF NOT EXISTS ix_raw_error_detail_code    ON raw.error_detail (error_code);

CREATE INDEX IF NOT EXISTS ix_raw_txn_val_batch        ON raw.transaction_validation (batch_id);
CREATE INDEX IF NOT EXISTS ix_raw_txn_val_skey         ON raw.transaction_validation (transaction_val_skey);
CREATE INDEX IF NOT EXISTS ix_raw_txn_val_error_fk     ON raw.transaction_validation (error_detail_skey_fk);
CREATE INDEX IF NOT EXISTS ix_raw_txn_val_created      ON raw.transaction_validation (created_date);

CREATE INDEX IF NOT EXISTS ix_raw_rule_batch           ON raw.validation_rule (batch_id);
CREATE INDEX IF NOT EXISTS ix_raw_rule_skey            ON raw.validation_rule (rule_skey);

CREATE INDEX IF NOT EXISTS ix_raw_file_batch           ON raw.file_registry (batch_id);
CREATE INDEX IF NOT EXISTS ix_raw_file_skey            ON raw.file_registry (file_skey);