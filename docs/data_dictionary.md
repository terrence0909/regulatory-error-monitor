# Data dictionary

Plain-English meaning of every column. Where a meaning is a guess from the column name, it is marked **Assumed**.

Every raw table also has two columns added by the loader: `batch_id` (which load brought the row in) and `loaded_at` (when).

Raw tables have no enforced primary keys on purpose. The same row can arrive more than once (a repeated file, or a cleared error sent again), and raw keeps everything. Duplicates are removed in staging.

## raw.error_detail

The lookup of error codes. One row per version of an error code.

| Column | Type | Meaning |
|---|---|---|
| error_detail_skey | integer | Key for this version of the error. |
| error_code | text | The short code people use for the error, such as `E1042`. Shared by all versions of the same error. |
| source_row_id | text | ID of the row in the original system. Used only for tracing. **Assumed.** |
| error_description | text | What the error means, in words. This is the text that changes between versions. |
| response | text | What the person should do about it. |
| error_level | text | How serious it is, for example warning, error or critical. |
| error_type | text | The kind of problem, for example format, limit or missing value. |
| active_date | date | The day this version became the one in use. |
| inactive_date | date | The day this version stopped being used. Empty for the current version. |
| created_date | timestamp | When the row was first created. |
| created_by | text | Who or what created it. |
| updated_date | timestamp | When the row was last changed. |
| updated_by | text | Who or what last changed it. |

## raw.transaction_validation

One row per validation error found on a payment line.

| Column | Type | Meaning |
|---|---|---|
| transaction_val_skey | bigint | Key for this row. A cleared error is sent again with the same key. |
| error_detail_skey_fk | integer | Which error version was raised. Points to `error_detail`. |
| file_skey_fk | integer | Which received file the payment came in. Points to `file_registry`. |
| message_identification | text | ID of the payment message. **Assumed** to be the batch-level message ID. |
| end_to_end_identification | text | ID that follows one payment from start to finish. **Assumed.** |
| rule_skey_fk | integer | Which rule found the error. Points to `validation_rule`. |
| sequence_number | integer | Position of the payment within the file. **Assumed.** |
| sub_sequence | integer | Position within a split or grouped payment. **Assumed.** |
| line_number | integer | Line within the payment where the error was found. |
| entity_code | text | Short code of the reporting entity (the institution sending the report). |
| entity_name | text | Name of the reporting entity. |
| reporting_attribute | text | The field in the report that failed. **Assumed.** |
| reporting_component | text | The section of the report that field belongs to. **Assumed.** |
| report_reference_number | text | Reference number of the report this belongs to. **Assumed.** |
| report_start_datetime | timestamp | When the report run started. **Assumed.** |
| reporting_qualifier | text | A label that qualifies the type of report. **Assumed.** |
| flow | text | Direction of the payment, for example inward or outward. **Assumed.** |
| original_file_reference | text | The name or reference of the file as received. |
| error_status | text | Current state of the error. |
| error_number | integer | Count or ID of this error within the transaction. **Assumed.** |
| user_id | text | Who last handled the row. |
| transaction_error_id | text | An ID for this specific error on this specific transaction. |
| external_ref_number | text | Reference used by an outside system. |
| transaction_type | text | The kind of payment. |
| error_type | text | Repeats `error_detail.error_type`. Not trusted: staging uses the lookup. |
| error_description | text | Repeats `error_detail.error_description`. Not trusted: staging uses the lookup. |
| last_update_date | timestamp | When the row was last changed in the source. |
| processed_date | date | The day the error was cleared. Empty while still open. |
| processed_date_time | timestamp | The exact time it was cleared. More precise than `processed_date`. |
| created_date | timestamp | When the row was first created. |
| created_by | text | Who or what created it. |
| updated_date | timestamp | When the row was last changed. |
| updated_by | text | Who or what last changed it. |
| transaction_status | text | The overall state of the payment (not just this error). |

## raw.validation_rule (invented for this project)

| Column | Type | Meaning |
|---|---|---|
| rule_skey | integer | Key for the rule. |
| rule_code | text | Short code of the rule. |
| rule_name | text | Plain-English name. |
| rule_category | text | Group the rule belongs to, for example amount, currency or format. |
| updated_date | timestamp | When this version of the rule was last changed. Rules are renamed in place, and each version arrives as its own row, so dbt can work out the history. |

## raw.file_registry (invented for this project)

| Column | Type | Meaning |
|---|---|---|
| file_skey | integer | Key for the file. |
| file_name | text | Name of the file. |
| received_at | timestamp | When the file arrived. |
| row_count | integer | How many rows the file claimed to contain. Used to check the load. |

## Audit and quarantine tables

### audit.load_log

| Column | Meaning |
|---|---|
| batch_id | The load this row describes |
| source_file | The file loaded |
| rows_read | Rows found in the file |
| rows_loaded | Rows that passed checks and were loaded |
| rows_rejected | Rows sent to quarantine |
| seconds_taken | How long the load took |
| logged_at | When this row was written |

### quarantine.rejected_rows

| Column | Meaning |
|---|---|
| batch_id | The load the row came from |
| table_name | Which raw table it was meant for |
| row_as_text | The row exactly as received, kept as text |
| reason | Why it was rejected, in plain English |
| rejected_at | When it was rejected |

## Marts layer columns that are calculated

| Column | How it is worked out |
|---|---|
| is_open | `processed_at` is empty |
| days_to_clear | `processed_at - created_at` in days. Empty while the error is still open. |
| valid_from, valid_to | From `active_date` and `inactive_date` for errors (`valid_to` is `9999-12-31` for the current version). For rules, from each version's own date until the day before the next version. |
| is_current | `valid_to` is `9999-12-31` |
| created_date_key | The created date as a number like `20260115` |
| processed_at | `processed_date_time` when present, otherwise `processed_date` |
| batch_date | The day of the batch that last delivered this row |