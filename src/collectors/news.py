"""기업 뉴스 수집기 (Google News RSS).

동작 방식
---------
1. 기업별로 별칭을 OR 로 묶어 Google News RSS 를 조회한다
   (예: "린데코리아" OR "Linde Korea" OR ... when:7d).
2. 제목에 별칭이 들어 있는 기사를 우선하고, 모자라면 본문 언급 기사로 채운다.
   Google News 는 회사가 본문에 스치듯 언급된 기사도 물어오기 때문이다
   (실측: '조선내화' 검색 결과에 지자체 폭염 대응 기사가 섞여 나옴).
3. 같은 기사가 여러 기업 피드에 걸리면 하나로 합치고 companies 를 병합한다.

레코드 스키마:
    {
        "companies": list[str],   # config.COMPANIES 의 key, 1개 이상
        "title": str,
        "source": str,            # 매체명
        "published": str,         # KST 기준 YYYY-MM-DD
        "published_at": str,      # KST ISO 8601
        "url": str,
        "summary": str,
        "title_match": bool,      # 제목에 회사명이 있으면 True (본문 언급이면 False)
    }

CLI:
    python -m src.collectors.news --days 7
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

from src import config
from src.text import clean_text

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=config.KST_OFFSET_HOURS))


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _session() -> requests.Session:
    s = requests.Session()
    # 기본 python-requests UA 로는 Google News 가 빈 피드를 주는 경우가 있다
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    return s


def build_query(company: dict, lookback_days: int) -> str:
    """별칭을 OR 로 묶고 기간 제한을 붙인 검색식."""
    aliases = " OR ".join(f'"{a}"' for a in company["aliases"])
    return f"({aliases}) when:{lookback_days}d"


def fetch_feed(session: requests.Session, query: str) -> list[dict]:
    """Google News RSS 조회. 실패하면 빈 리스트."""
    params = {"q": query, **config.NEWS_LOCALE}
    url = f"{config.GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"

    for attempt in range(config.MAX_RETRIES):
        try:
            resp = session.get(url, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code >= 500 or resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return feedparser.parse(resp.content).entries
        except requests.RequestException as exc:
            if attempt == config.MAX_RETRIES - 1:
                print(f"  [warn] RSS 조회 실패: {exc}", file=sys.stderr)
                return []
            time.sleep(2 ** attempt)
    return []


# ---------------------------------------------------------------------------
# 엔트리 -> 내부 스키마
# ---------------------------------------------------------------------------
def _published_kst(entry: dict) -> tuple[str, str]:
    """RSS 의 GMT 시각을 KST 로 변환해 (날짜, ISO 타임스탬프) 반환."""
    parsed = entry.get("published_parsed")
    if not parsed:
        return "", ""
    utc = datetime(*parsed[:6], tzinfo=timezone.utc)
    kst = utc.astimezone(KST)
    return kst.date().isoformat(), kst.isoformat()


def _source_name(entry: dict) -> str:
    source = entry.get("source")
    if isinstance(source, dict):
        return clean_text(source.get("title", ""))
    return clean_text(getattr(source, "title", "") if source else "")


def _strip_source_suffix(title: str, source: str) -> str:
    """Google News 제목 끝의 ' - 매체명' 제거 (매체명은 따로 보관한다)."""
    suffix = f" - {source}"
    return title[: -len(suffix)] if source and title.endswith(suffix) else title


def is_market_noise(title: str) -> bool:
    """자동생성 주가·시황 기사인지 판정."""
    return any(term in title for term in config.NEWS_EXCLUDE_TITLE_TERMS)


def to_record(entry: dict, company_key: str, aliases: list[str]) -> dict | None:
    """RSS 엔트리 -> 내부 레코드."""
    source = _source_name(entry)
    title = _strip_source_suffix(clean_text(entry.get("title", "")), source)
    if not title or is_market_noise(title):
        return None

    published, published_at = _published_kst(entry)

    # RSS 요약문은 원문 링크 <a> 태그뿐이라 태그를 벗기면 제목만 남는다.
    summary = clean_text(entry.get("summary", ""))
    if summary == title or summary.startswith(title):
        summary = ""

    return {
        "companies": [company_key],
        "title": title,
        "source": source,
        "published": published,
        "published_at": published_at,
        "url": entry.get("link", ""),
        "summary": summary,
        "title_match": any(a.lower() in title.lower() for a in aliases),
    }


def rank_and_cap(records: list[dict], limit: int, body_only_limit: int) -> list[dict]:
    """제목 매칭 기사를 먼저 채우고, 남는 자리만 본문 언급 기사로 채운다.

    본문 언급은 관련도가 크게 떨어져 별도 상한을 둔다.
    """
    by_recency = sorted(records, key=lambda r: r["published_at"], reverse=True)
    titled = [r for r in by_recency if r["title_match"]]
    body_only = [r for r in by_recency if not r["title_match"]]

    picked = titled[:limit]
    room = min(limit - len(picked), body_only_limit)
    return picked + body_only[:room]


def merge_duplicates(records: list[dict]) -> list[dict]:
    """같은 기사가 여러 기업 피드에 걸린 경우 companies 를 합친다.

    제목을 우선 키로 쓴다. Google News 링크는 리다이렉트 토큰이라 같은 기사도
    주소가 다를 수 있어(실측: 동일 제목·동일 매체 기사가 서로 다른 URL로 2건)
    URL 로만 묶으면 중복이 남는다. 뒤에 오는 dedupe_news 와 기준을 맞춘다.
    """
    from src.processors.dedupe import normalize_url
    from src.text import normalize_title

    merged: dict[str, dict] = {}
    for rec in records:
        key = normalize_title(rec["title"]) or normalize_url(rec["url"])
        if key in merged:
            existing = merged[key]
            for company in rec["companies"]:
                if company not in existing["companies"]:
                    existing["companies"].append(company)
            existing["title_match"] = existing["title_match"] or rec["title_match"]
        else:
            merged[key] = {**rec, "companies": list(rec["companies"])}
    return list(merged.values())


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def _fetch_window(
    session: requests.Session, company: dict, window_days: int, today: date
) -> list[dict]:
    """한 회사를 지정한 창으로 조회해 레코드 리스트로."""
    since = (today - timedelta(days=window_days)).isoformat()
    entries = fetch_feed(session, build_query(company, window_days))

    records = []
    for entry in entries:
        rec = to_record(entry, company["key"], company["aliases"])
        # when:Nd 로 걸러지지만 경계에서 새는 경우가 있어 한 번 더 확인
        if rec and rec["published"] and rec["published"] >= since:
            rec["window_days"] = window_days
            records.append(rec)
    return records


def collect(lookback_days: int = config.LOOKBACK_DAYS, *, today: date | None = None) -> list[dict]:
    """기업별 최신 뉴스를 수집해 레코드 리스트로 반환.

    기본 창에서 제목 매칭 기사가 하나도 안 나오면 창을 넓혀 재조회한다.
    """
    until = today or date.today()
    session = _session()
    collected: list[dict] = []

    for company in config.COMPANIES:
        windows = [lookback_days, *config.NEWS_FALLBACK_DAYS]
        records: list[dict] = []
        used = lookback_days

        for window in windows:
            records = _fetch_window(session, company, window, until)
            used = window
            if any(r["title_match"] for r in records):
                break
            time.sleep(config.REQUEST_DELAY)

        picked = rank_and_cap(records, config.MAX_NEWS_PER_COMPANY, config.MAX_BODY_ONLY_NEWS)
        notes = []
        if used != lookback_days:
            notes.append(f"{used}일까지 확대")
        body_only = sum(1 for r in picked if not r["title_match"])
        if body_only:
            notes.append(f"본문 언급 {body_only}건")
        note = f" ({', '.join(notes)})" if notes else ""
        print(f"  {company['label']}: {len(picked)}건{note}")
        collected.extend(picked)

        time.sleep(config.REQUEST_DELAY)

    return merge_duplicates(collected)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def run(days: int = config.LOOKBACK_DAYS, *, archive: bool = True) -> list[dict]:
    """수집 -> 중복 제거 -> (선택) 주차 아카이브 저장."""
    from src.processors import dedupe

    print(f"기업 {len(config.COMPANIES)}곳, 최근 {days}일")
    records = collect(days)
    seen = dedupe.load_seen_news(ROOT / config.NEWS_DIR)
    fresh = dedupe.dedupe_news(records, seen)

    print(f"\n수집 {len(records)}건 -> 중복 제거 {len(fresh)}건")
    for company in config.COMPANIES:
        n = sum(1 for r in fresh if company["key"] in r["companies"])
        print(f"  {company['label']}: {n}건")

    if archive:
        today = date.today()
        year, week, _ = today.isocalendar()
        out = ROOT / config.NEWS_DIR / f"{year}-W{week:02d}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "collected_at": today.isoformat(),
            "lookback_days": days,
            "count": len(fresh),
            "news": fresh,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"저장: {out.relative_to(ROOT)}")

    return fresh


def main() -> int:
    parser = argparse.ArgumentParser(description="기업 뉴스 수집 (Google News RSS)")
    parser.add_argument("--days", type=int, default=config.LOOKBACK_DAYS,
                        help=f"조회 기간(일), 기본 {config.LOOKBACK_DAYS}")
    parser.add_argument("--no-archive", action="store_true",
                        help="파일로 저장하지 않고 결과만 출력")
    args = parser.parse_args()

    run(args.days, archive=not args.no_archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
