"""
Tests for the small, pure helpers: password hashing, interest encoding,
HH:MM parsing/validation, bearer parsing, etc.
"""
import base64

import pytest
from fastapi import HTTPException

import main


# ---------- password helpers ----------

def test_new_salt_is_base64_and_unique():
    a = main._new_salt_b64()
    b = main._new_salt_b64()
    assert a != b
    # Must round-trip through base64 without error.
    assert len(base64.b64decode(a)) == 16
    assert len(base64.b64decode(b)) == 16


def test_hash_password_is_deterministic_for_same_salt():
    salt = main._new_salt_b64()
    h1 = main._hash_password("hunter22!", salt)
    h2 = main._hash_password("hunter22!", salt)
    assert h1 == h2


def test_hash_password_changes_with_salt():
    pw = "hunter22!"
    h1 = main._hash_password(pw, main._new_salt_b64())
    h2 = main._hash_password(pw, main._new_salt_b64())
    assert h1 != h2


def test_hash_password_changes_with_password():
    salt = main._new_salt_b64()
    assert main._hash_password("a", salt) != main._hash_password("b", salt)


# ---------- interest encoding ----------

def test_encode_decode_interests_roundtrip():
    interests = ["food", "coffee", "museums"]
    raw = main._encode_interests(interests)
    assert main._decode_interests(raw) == interests


def test_encode_interests_handles_empty():
    assert main._encode_interests([]) == "[]"
    assert main._encode_interests(None) == "[]"  # falsy -> []


def test_decode_interests_handles_none_and_blank():
    assert main._decode_interests(None) == []
    assert main._decode_interests("") == []


def test_decode_interests_returns_empty_on_garbage():
    assert main._decode_interests("not json") == []
    # JSON but not a list -> empty
    assert main._decode_interests('{"k":"v"}') == []


def test_decode_interests_coerces_items_to_str():
    assert main._decode_interests("[1, 2, \"x\"]") == ["1", "2", "x"]


# ---------- validate_hhmm ----------

def test_validate_hhmm_accepts_valid():
    assert main.validate_hhmm("00:00") == "00:00"
    assert main.validate_hhmm("09:30") == "09:30"
    assert main.validate_hhmm("23:59") == "23:59"


def test_validate_hhmm_passes_through_empty_and_none():
    assert main.validate_hhmm(None) is None
    assert main.validate_hhmm("") == ""


@pytest.mark.parametrize(
    "bad",
    ["9:30", "09:3", "9:3", "0930", "abc", "24:00", "12:60", "-1:00", "12:99"],
)
def test_validate_hhmm_rejects_bad_format_or_range(bad):
    with pytest.raises(HTTPException) as exc:
        main.validate_hhmm(bad)
    assert exc.value.status_code == 400


# ---------- validate_time_range ----------

def test_validate_time_range_ok_when_departure_after_arrival():
    # Should not raise.
    main.validate_time_range("09:00", "10:00")


def test_validate_time_range_rejects_equal_times():
    with pytest.raises(HTTPException) as exc:
        main.validate_time_range("09:00", "09:00")
    assert exc.value.status_code == 400


def test_validate_time_range_rejects_departure_before_arrival():
    with pytest.raises(HTTPException) as exc:
        main.validate_time_range("12:00", "11:00")
    assert exc.value.status_code == 400


def test_validate_time_range_skips_when_either_missing():
    # Both no-ops, no exception.
    main.validate_time_range(None, "10:00")
    main.validate_time_range("09:00", None)
    main.validate_time_range(None, None)
    main.validate_time_range("", "10:00")


# ---------- bearer parser ----------

def test_parse_bearer_extracts_token():
    assert main._parse_bearer("Bearer abc123") == "abc123"
    # Case insensitive scheme.
    assert main._parse_bearer("bearer abc123") == "abc123"


def test_parse_bearer_handles_bad_input():
    assert main._parse_bearer(None) is None
    assert main._parse_bearer("") is None
    assert main._parse_bearer("abc123") is None         # missing scheme
    assert main._parse_bearer("Basic abc123") is None   # wrong scheme
    assert main._parse_bearer("Bearer ") is None        # empty token


# ---------- hhmm <-> minutes ----------

def test_hhmm_to_minutes():
    assert main.hhmm_to_minutes("00:00") == 0
    assert main.hhmm_to_minutes("01:30") == 90
    assert main.hhmm_to_minutes("23:59") == 23 * 60 + 59


def test_minutes_to_hhmm():
    assert main.minutes_to_hhmm(0) == "00:00"
    assert main.minutes_to_hhmm(90) == "01:30"
    assert main.minutes_to_hhmm(23 * 60 + 59) == "23:59"


def test_minutes_to_hhmm_pads_single_digit_minutes():
    assert main.minutes_to_hhmm(605) == "10:05"


def test_hhmm_minutes_round_trip():
    for m in (0, 1, 60, 90, 540, 1439):
        assert main.hhmm_to_minutes(main.minutes_to_hhmm(m)) == m


# ---------- parse_clock_to_minutes ----------

def test_parse_clock_handles_am_pm():
    assert main.parse_clock_to_minutes("9:00 AM") == 9 * 60
    assert main.parse_clock_to_minutes("12:00 AM") == 0
    assert main.parse_clock_to_minutes("12:00 PM") == 12 * 60
    assert main.parse_clock_to_minutes("1:30 PM") == 13 * 60 + 30
    assert main.parse_clock_to_minutes("11:59 PM") == 23 * 60 + 59


def test_parse_clock_strips_dots_and_whitespace():
    # The function uppercases, removes whitespace, and strips dots.
    assert main.parse_clock_to_minutes("9:00 a.m.") == 9 * 60
    assert main.parse_clock_to_minutes("9:00am") == 9 * 60


def test_parse_clock_returns_none_on_bad_input():
    assert main.parse_clock_to_minutes("") is None
    assert main.parse_clock_to_minutes(None) is None
    assert main.parse_clock_to_minutes("noon") is None
    # 24h input without meridiem isn't supported.
    assert main.parse_clock_to_minutes("13:00") is None


# ---------- parse_google_duration_to_minutes ----------

def test_parse_google_duration_basic():
    assert main.parse_google_duration_to_minutes("60s") == 1
    assert main.parse_google_duration_to_minutes("120s") == 2
    # Rounds up partial minutes.
    assert main.parse_google_duration_to_minutes("61s") == 2
    assert main.parse_google_duration_to_minutes("735s") == 13


def test_parse_google_duration_handles_invalid():
    assert main.parse_google_duration_to_minutes(None) is None
    assert main.parse_google_duration_to_minutes("") is None
    assert main.parse_google_duration_to_minutes("60") is None      # missing trailing s
    assert main.parse_google_duration_to_minutes("abcs") is None    # not a number


# ---------- estimate_price_score ----------

def test_estimate_price_score_uses_price_level_when_int():
    assert main.estimate_price_score({"price_level": 0}) == 1
    assert main.estimate_price_score({"price_level": 4}) == 9


def test_estimate_price_score_falls_back_to_keywords():
    assert main.estimate_price_score({"name": "Fine Dining Steakhouse"}) == 8
    assert main.estimate_price_score({"name": "Joe's Bistro"}) == 5
    assert main.estimate_price_score({"name": "Riverside Park"}) == 3


def test_estimate_price_score_default_when_unknown():
    assert main.estimate_price_score({"name": "Unknown Foo Place"}) == 5


# ---------- get_real_weekday_index ----------

def test_get_real_weekday_index_with_known_date():
    # 2024-01-01 was a Monday -> weekday() == 0.
    assert main.get_real_weekday_index("2024-01-01", 0) == 0
    assert main.get_real_weekday_index("2024-01-01", 1) == 1  # Tuesday
    assert main.get_real_weekday_index("2024-01-01", 6) == 6  # Sunday


def test_get_real_weekday_index_handles_bad_date():
    # Invalid string falls back to "today" — just confirm we get a valid weekday.
    out = main.get_real_weekday_index("not-a-date", 0)
    assert 0 <= out <= 6


def test_get_real_weekday_index_handles_none_start_date():
    out = main.get_real_weekday_index(None, 0)
    assert 0 <= out <= 6
