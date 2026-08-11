"""수집기 공용 텍스트 정제 유틸."""

from __future__ import annotations

import html
import re

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def clean_text(s: str) -> str:
    """태그 제거 + HTML 엔티티 복원 + 공백 정리.

    Crossref 는 'Journal of the American\\nChemical Society',
    'Environmental Science &amp; Technology' 처럼 내려주고,
    RSS 요약문에는 <a> 태그가 그대로 들어 있다.
    """
    return WS.sub(" ", html.unescape(TAG.sub(" ", s or ""))).strip()


def normalize_title(s: str) -> str:
    """중복 판정용 제목 정규화 (공백·기호 제거 후 소문자)."""
    return re.sub(r"[^0-9a-z가-힣]", "", clean_text(s).lower())
