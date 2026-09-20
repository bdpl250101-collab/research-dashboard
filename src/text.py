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


# 짧은 라틴 별칭(SK, LS, E1 …)은 앞뒤에 라틴 문자·숫자가 없을 때만 인정한다.
# 그냥 부분 문자열로 찾으면 'TOOLS'·'desk' 가 걸리고, 정규식 \b 는 한글이 단어 문자로
# 취급돼 'SK하이닉스'·'LS전선' 에서 경계가 생기지 않아 쓸 수 없다.
_LATIN_SHORT = re.compile(r"^[A-Za-z0-9\-]{1,4}$")


def alias_pattern(alias: str) -> re.Pattern | None:
    """짧은 라틴 별칭이면 경계 조건을 건 패턴, 아니면 None(부분 문자열로 처리)."""
    if not _LATIN_SHORT.match(alias):
        return None
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
                      re.IGNORECASE)


def alias_matches(text: str, aliases: list[str]) -> bool:
    """text 가 별칭 중 하나에 해당하는지. 회사명·기사 제목 모두에 쓴다."""
    if not text:
        return False
    lowered = text.lower()
    for alias in aliases:
        pattern = alias_pattern(alias)
        if pattern is not None:
            if pattern.search(text):
                return True
        elif alias.lower() in lowered:
            return True
    return False
