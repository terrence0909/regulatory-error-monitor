"""Unit tests for the row checks. They need no database. Run: python3 -m pytest"""
from datetime import date

from generator.generate import TRANSACTION_COLS
from loader import validators as v


def good_row(**changes):
    row = {c: "" for c in TRANSACTION_COLS}
    row.update({
        "transaction_val_skey": "10", "error_detail_skey_fk": "1", "file_skey_fk": "5",
        "rule_skey_fk": "2", "created_date": "2026-01-10 09:30:00",
    })
    row.update(changes)
    return row


def ctx():
    return v.BatchContext(date(2026, 1, 10), error_keys={1, 2}, rule_keys={2}, file_keys={5})


def run(row, context=None):
    return v.check_transaction(row, context or ctx(), TRANSACTION_COLS)


def test_good_row_passes():
    assert run(good_row()) is None


def test_missing_row_key():
    assert run(good_row(transaction_val_skey="")) == v.NO_ROW_KEY


def test_missing_error_key():
    assert run(good_row(error_detail_skey_fk="")) == v.NO_ERROR_KEY


def test_unknown_error_key():
    assert run(good_row(error_detail_skey_fk="99999")) == v.ERROR_KEY_UNKNOWN


def test_unknown_rule_and_file_keys():
    assert run(good_row(rule_skey_fk="77")) == v.RULE_KEY_UNKNOWN
    assert run(good_row(file_skey_fk="77")) == v.FILE_KEY_UNKNOWN


def test_future_created_date():
    assert run(good_row(created_date="2026-02-09 09:30:00")) == v.FUTURE_CREATED


def test_created_today_is_fine_and_late_arrival_is_fine():
    assert run(good_row(created_date="2026-01-10 23:59:59")) is None
    assert run(good_row(created_date="2026-01-08 09:00:00")) is None


def test_processed_before_created():
    row = good_row(processed_date="2026-01-08")
    assert run(row) == v.PROCESSED_BEFORE_CREATED


def test_processed_same_day_is_fine():
    assert run(good_row(processed_date="2026-01-10")) is None


def test_unreadable_values():
    assert run(good_row(rule_skey_fk="abc")) == v.BAD_VALUE.format(col="rule_skey_fk")
    assert run(good_row(created_date="yesterday")) == v.BAD_VALUE.format(col="created_date")


def test_exact_duplicate_is_caught_but_first_copy_passes():
    context = ctx()
    assert run(good_row(), context) is None
    assert run(good_row(), context) == v.DUPLICATE


def test_changed_row_is_not_a_duplicate():
    context = ctx()
    assert run(good_row(), context) is None
    assert run(good_row(processed_date="2026-01-10"), context) is None


def test_a_bad_row_is_not_remembered_for_duplicates():
    context = ctx()
    assert run(good_row(error_detail_skey_fk="99999"), context) == v.ERROR_KEY_UNKNOWN
    assert run(good_row(error_detail_skey_fk="99999"), context) == v.ERROR_KEY_UNKNOWN


def test_error_detail_checks():
    ok = {"error_detail_skey": "1", "error_code": "E1001", "active_date": "2025-07-01", "inactive_date": ""}
    assert v.check_error_detail(ok) is None
    assert v.check_error_detail({**ok, "error_code": ""}) == v.MISSING_REQUIRED.format(col="error_code")
    assert v.check_error_detail({**ok, "inactive_date": "2025-06-01"}) == v.BAD_DATE_ORDER