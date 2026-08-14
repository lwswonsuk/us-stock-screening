"""
quotes.py — 소제목에 표시할 투자자 명언 (ISO 주차 기준 매주 전환)
"""

from __future__ import annotations

from datetime import date

QUOTES: list[dict] = [
    {"text": "가격은 당신이 지불하는 것이고, 가치는 당신이 얻는 것이다.", "author": "Warren Buffett"},
    {"text": "위험은 가격에서 온다. 좋은 자산도 비싸게 사면 위험해진다.", "author": "Howard Marks"},
    {"text": "인생에서 몇 번의 위대한 결정만 내리고 나머지는 인내하면 된다.", "author": "Mohnish Pabrai"},
    {"text": "훌륭한 회사를 적정한 가격에 사는 것이, 적당한 회사를 훌륭한 가격에 사는 것보다 낫다.", "author": "Charlie Munger"},
    {"text": "확신이 있는 소수의 아이디어에 집중하고, 나머지는 무시하라.", "author": "Bill Ackman"},
    {"text": "당신이 아는 것에 투자하라. 모르는 것에 투자하지 마라.", "author": "Peter Lynch"},
    {"text": "안전마진이 있는 곳에서만 투자하라. 나머지는 투기다.", "author": "Seth Klarman"},
    {"text": "훌륭한 경영진이 이끄는 성장 기업을 찾아, 오래 보유하라.", "author": "Philip Fisher"},
    {"text": "시장의 변덕이 아니라 기업의 가치를 사라.", "author": "Benjamin Graham"},
    {"text": "10년을 보유할 생각이 없다면 단 10분도 보유하지 마라.", "author": "Warren Buffett"},
    {"text": "장기적으로 시장을 이기는 유일한 방법은 남들과 다르게 행동하는 것이다.", "author": "John Templeton"},
    {"text": "복리는 세계 8대 불가사의다. 이해하는 자는 이익을 얻고, 모르는 자는 대가를 치른다.", "author": "Albert Einstein"},
]


def pick_quote_for_week(today: date | None = None) -> dict:
    """ISO 주차(연도+주차) 기준으로 명언을 결정적으로 선택한다.
    같은 주 안에는 매일 갱신이 돌아도 동일한 명언이 유지된다."""
    if today is None:
        today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    idx = (iso_year * 53 + iso_week) % len(QUOTES)
    return QUOTES[idx]
