"""
Row checks for the loader (phase 4).

Every function here takes one row (a dict of text values, exactly as read from
the CSV) and returns None if the row is fine, or a plain-English reason if it
must go to quarantine. Nothing in this file touches the database, so it is easy
to test.

A row gets at most one reason: the first check it fails.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

# Reasons shown in quarantine.rejected_rows
NO_ROW_KEY = "Missing row key (transaction_val_skey is empty)"
NO_ERROR_KEY = "Missing link to the error lookup (error_detail_skey_fk is empty)"
ERROR_KEY_UNKNOWN = "Error key not found in the error lookup"
RULE_KEY_UNKNOWN = "Rule key not found in the rule table"
FILE_KEY_UNKNOWN = "File key not found in the file registry"
FUTURE_CREATED = "Created date is in the future"
PROCESSED_BEFORE_CREATED = "Processed date is earlier than the created date"
DUPLICATE = "Exact duplicate of another row in the same batch"
BAD_VALUE = "Value could not be read in column {col}"
MISSING_REQUIRED = "Required column {col} is empty"
BAD_DATE_ORDER = "Inactive date is earlier than the active date"

# Used by verify_load.py to match quarantine reasons with the generator's manifest
REASON_TO_PLANTED_KIND = {
    NO_ROW_KEY: "null_row_key",
    NO_ERROR_KEY: "null_error_key",
    ERROR_KEY_UNKNOWN: "orphan_error_key",
    FUTURE_CREATED: "future_created_date",
    PROCESSED_BEFORE_CREATED: "processed_before_created",
    DUPLICATE: "duplicate_row",
}


class _BadValue(Exception):
    def __init__(self, col: str):
        super().__init__(col)
        self.col = col


def to_int(row: dict, col: str) -> int:
    try:
        return int(str(row[col]).strip())
    except (ValueError, KeyError):
        raise _BadValue(col)


def to_datetime(row: dict, col: str) -> datetime:
    text = str(row.get(col, "")).strip()
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d")
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise _BadValue(col)


class BatchContext:
    """What the transaction checks need to know about the batch being loaded."""

    def __init__(self, batch_date: date, error_keys, rule_keys, file_keys):
        self.batch_date = batch_date
        self.error_keys = set(error_keys)
        self.rule_keys = set(rule_keys)
        self.file_keys = set(file_keys)
        self._seen = set()


def check_transaction(row: dict, ctx: BatchContext, columns) -> Optional[str]:
    if str(row["transaction_val_skey"]).strip() == "":
        return NO_ROW_KEY
    if str(row["error_detail_skey_fk"]).strip() == "":
        return NO_ERROR_KEY

    try:
        to_int(row, "transaction_val_skey")
        error_key = to_int(row, "error_detail_skey_fk")
        rule_key = to_int(row, "rule_skey_fk")
        file_key = to_int(row, "file_skey_fk")
        created = to_datetime(row, "created_date")
        processed = None
        if str(row["processed_date"]).strip() != "":
            processed = to_datetime(row, "processed_date")
        if str(row["processed_date_time"]).strip() != "":
            to_datetime(row, "processed_date_time")
    except _BadValue as bad:
        return BAD_VALUE.format(col=bad.col)

    if error_key not in ctx.error_keys:
        return ERROR_KEY_UNKNOWN
    if rule_key not in ctx.rule_keys:
        return RULE_KEY_UNKNOWN
    if file_key not in ctx.file_keys:
        return FILE_KEY_UNKNOWN
    if created.date() > ctx.batch_date:
        return FUTURE_CREATED
    if processed is not None and processed.date() < created.date():
        return PROCESSED_BEFORE_CREATED

    fingerprint = tuple(row[c] for c in columns)
    if fingerprint in ctx._seen:
        return DUPLICATE
    ctx._seen.add(fingerprint)
    return None


def check_error_detail(row: dict) -> Optional[str]:
    for col in ("error_detail_skey", "error_code", "active_date"):
        if str(row[col]).strip() == "":
            return MISSING_REQUIRED.format(col=col)
    try:
        to_int(row, "error_detail_skey")
        active = to_datetime(row, "active_date")
        if str(row["inactive_date"]).strip() != "":
            if to_datetime(row, "inactive_date") < active:
                return BAD_DATE_ORDER
    except _BadValue as bad:
        return BAD_VALUE.format(col=bad.col)
    return None


def check_rule(row: dict) -> Optional[str]:
    for col in ("rule_skey", "rule_code"):
        if str(row[col]).strip() == "":
            return MISSING_REQUIRED.format(col=col)
    try:
        to_int(row, "rule_skey")
    except _BadValue as bad:
        return BAD_VALUE.format(col=bad.col)
    return None


def check_file(row: dict) -> Optional[str]:
    for col in ("file_skey", "file_name"):
        if str(row[col]).strip() == "":
            return MISSING_REQUIRED.format(col=col)
    try:
        to_int(row, "file_skey")
        to_int(row, "row_count")
    except _BadValue as bad:
        return BAD_VALUE.format(col=bad.col)
    return None
