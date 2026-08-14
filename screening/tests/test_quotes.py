from datetime import date

from quotes import QUOTES, pick_quote_for_week


def test_quote_count_is_at_least_ten():
    assert len(QUOTES) >= 10


def test_same_iso_week_returns_same_quote():
    mon = date(2026, 8, 10)
    fri = date(2026, 8, 14)
    assert pick_quote_for_week(mon) == pick_quote_for_week(fri)


def test_different_iso_week_can_return_different_quote():
    idx33 = (2026 * 53 + 33) % len(QUOTES)
    idx34 = (2026 * 53 + 34) % len(QUOTES)
    assert idx33 != idx34
    assert pick_quote_for_week(date(2026, 8, 10)) == QUOTES[idx33]


def test_returns_text_and_author_keys():
    q = pick_quote_for_week(date(2026, 1, 1))
    assert set(q.keys()) == {"text", "author"}
