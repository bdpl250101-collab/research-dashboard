"""중복 제거 및 정규화.

논문은 DOI, 뉴스는 URL(정규화 후)을 1차 키로 사용한다.
주차별 아카이브(data/papers, data/news)와 대조해 이미 노출된 항목은 제외한다.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_DOI_PREFIX = re.compile(r"^(https?://)?(dx\.)?doi\.org/", re.IGNORECASE)


def archive_name(today: date) -> str:
    """주차 아카이브 파일명. 저장과 중복 제거가 같은 규칙을 쓰도록 한 곳에 둔다."""
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}.json"


def normalize_doi(doi: str) -> str:
    """'https://doi.org/10.1000/ABC' -> '10.1000/abc'"""
    return _DOI_PREFIX.sub("", (doi or "").strip()).lower().rstrip("/")


def load_seen_dois(archive_dir: Path | str, *, exclude: str | None = None) -> set[str]:
    """주차별 아카이브 JSON을 훑어 이미 수집한 DOI 집합을 만든다.

    exclude 에는 지금 쓰는 중인 주차 파일명을 넘긴다. 넘기지 않으면 같은 주에
    재실행할 때 방금 저장한 결과가 '이미 노출됨' 으로 걸려서 전량 제거되고,
    그 빈 결과가 다시 그 주 아카이브를 덮어쓴다.
    """
    seen: set[str] = set()
    directory = Path(archive_dir)
    if not directory.exists():
        return seen

    for path in sorted(directory.glob("*.json")):
        if exclude and path.name == exclude:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for paper in payload.get("papers", []):
            doi = normalize_doi(paper.get("doi", ""))
            if doi:
                seen.add(doi)
    return seen


def dedupe_papers(records: list[dict], seen_dois: set[str]) -> list[dict]:
    """이전 주차에 이미 나온 논문과 이번 배치 내 중복을 제거한다.

    DOI가 없는 레코드는 제목(소문자·공백 제거)을 대체 키로 쓴다.
    """
    fresh: list[dict] = []
    batch_keys: set[str] = set()

    for rec in records:
        doi = normalize_doi(rec.get("doi", ""))
        key = doi or "title:" + re.sub(r"\s+", " ", rec.get("title", "").lower()).strip()
        if not key or key == "title:":
            continue
        if doi and doi in seen_dois:
            continue
        if key in batch_keys:
            continue
        batch_keys.add(key)
        fresh.append({**rec, "doi": doi})

    return fresh


def normalize_url(url: str) -> str:
    """추적 파라미터·fragment 제거 후 소문자 호스트로 정규화 (뉴스용)."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _news_keys(record: dict) -> tuple[str, str]:
    """(URL 키, 제목 키). 둘 중 하나만 걸려도 중복으로 본다.

    Google News 링크는 리다이렉트 토큰이라 같은 기사라도 주소가 달라질 수 있어
    제목 키를 함께 쓴다. 반대로 다른 매체가 같은 헤드라인을 쓰는 경우도
    같은 사안이므로 하나만 남기는 게 맞다.
    """
    from src.text import normalize_title

    return normalize_url(record.get("url", "")), normalize_title(record.get("title", ""))


def load_seen_news(archive_dir: Path | str, *, exclude: str | None = None) -> set[str]:
    """주차별 아카이브를 훑어 이미 노출한 뉴스의 URL·제목 키 집합을 만든다.

    exclude 의 의미는 load_seen_dois 와 같다 (현재 주차 파일 제외).
    """
    seen: set[str] = set()
    directory = Path(archive_dir)
    if not directory.exists():
        return seen

    for path in sorted(directory.glob("*.json")):
        if exclude and path.name == exclude:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for item in payload.get("news", []):
            url_key, title_key = _news_keys(item)
            if url_key:
                seen.add(url_key)
            if title_key:
                seen.add(title_key)
    return seen


def load_seen_job_ids(archive_dir: Path | str, *, exclude: str | None = None) -> set[str]:
    """직전까지 노출한 채용공고 번호 집합.

    논문·뉴스와 달리 이 집합은 **제외용이 아니라 신규 표시용**이다.
    채용공고는 마감 전이면 지난 주에 봤더라도 계속 보여줘야 한다.
    """
    seen: set[str] = set()
    directory = Path(archive_dir)
    if not directory.exists():
        return seen

    for path in sorted(directory.glob("*.json")):
        if exclude and path.name == exclude:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for job in payload.get("jobs", []):
            job_id = str(job.get("job_id", ""))
            if job_id:
                seen.add(job_id)
    return seen


def dedupe_news(records: list[dict], seen_urls: set[str]) -> list[dict]:
    """이전 주차에 이미 나온 기사와 이번 배치 내 중복을 제거한다."""
    fresh: list[dict] = []
    batch_keys: set[str] = set()

    for rec in records:
        url_key, title_key = _news_keys(rec)
        keys = {k for k in (url_key, title_key) if k}
        if not keys:
            continue
        if keys & seen_urls or keys & batch_keys:
            continue
        batch_keys |= keys
        fresh.append(rec)

    return fresh
