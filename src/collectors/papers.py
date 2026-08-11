"""논문 수집기 (Crossref REST API).

동작 방식
---------
1. config.JOURNALS 의 각 저널 ISSN을 확보한다 (없으면 Crossref journals API로 조회 후 캐시).
2. 저널별로 최근 N일간 Crossref에 **색인된** journal-article을 전부 가져온다.
   - 키워드로 검색하지 않고 저널 전체를 훑은 뒤 로컬에서 분류한다.
     Crossref의 키워드 검색은 관련도 기반이라 검색어가 본문에 없는 논문도
     섞여 들어오는데, 대상 저널이 10종 내외라 전량 조회가 더 정확하고 빠르다.
3. 제목/초록/키워드를 config.TOPICS 의 terms·acronyms와 대조해 주제를 붙인다.
4. 하나도 안 붙은 논문은 버린다.

레코드 스키마:
    {
        "topics": list[str],   # config.TOPICS 의 key, 1개 이상 (복수 주제 가능)
        "title": str,
        "authors": list[str],
        "journal": str,
        "published": str,      # ISO 8601 (YYYY-MM-DD)
        "doi": str,            # 소문자 정규화
        "url": str,
        "abstract": str,
    }

CLI:
    python -m src.collectors.papers --days 7
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from src import config
from src.text import TAG as _JATS_TAG, WS as _WS, clean_text

# 저장소 루트 (src/collectors/papers.py -> 상위 2단계)
ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _session() -> requests.Session:
    s = requests.Session()
    mailto = os.environ.get("CROSSREF_MAILTO", "").strip()
    ua = "research-dashboard/0.1 (https://github.com/; python-requests)"
    if mailto:
        ua = f"research-dashboard/0.1 (mailto:{mailto})"
    s.headers.update({"User-Agent": ua})
    return s


def _get(session: requests.Session, url: str, params: dict) -> dict:
    """Crossref GET + 429/5xx 재시도. 실패하면 마지막 예외를 그대로 올린다."""
    last_exc: Exception | None = None
    for attempt in range(config.MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(wait, 30))
                last_exc = RuntimeError(f"HTTP {resp.status_code} from {url}")
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Crossref 요청 실패: {url}") from last_exc


# ---------------------------------------------------------------------------
# 저널 ISSN 확보
# ---------------------------------------------------------------------------
def _norm_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_journals(session: requests.Session, *, refresh: bool = False) -> list[dict]:
    """config.JOURNALS 를 {name, title, issns} 리스트로 변환한다.

    config에 issn이 적혀 있으면 그대로 쓰고, 비어 있으면 Crossref journals API로
    조회한다. 결과는 data/journals.json 에 캐시한다 (자동 매칭 검수용).
    """
    cache_path = ROOT / config.JOURNAL_CACHE
    cache: dict = {}
    if cache_path.exists() and not refresh:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    resolved: list[dict] = []
    dirty = False

    for journal in config.JOURNALS:
        name = journal["name"]

        configured = journal.get("issn") or []
        if isinstance(configured, str):
            configured = [configured] if configured else []
        if configured:
            resolved.append({"name": name, "title": name, "issns": configured})
            continue

        if name in cache and cache[name].get("issns"):
            entry = cache[name]
            resolved.append({"name": name, "title": entry["title"], "issns": entry["issns"]})
            continue

        data = _get(session, f"{config.CROSSREF_API}/journals", {"query": name, "rows": 5})
        items = data.get("message", {}).get("items", [])

        # 제목이 정확히 일치할 때만 채택한다. 관련도 1위를 그냥 쓰면
        # 'Science' -> 'ScienceAsia' 같은 엉뚱한 저널이 조용히 섞인다.
        target = _norm_title(name)
        best = next((it for it in items if _norm_title(it.get("title", "")) == target), None)
        if best is None:
            found = ", ".join(repr(it.get("title")) for it in items[:3]) or "결과 없음"
            print(f"  [warn] ISSN 자동 조회 실패, 건너뜀: '{name}' (후보: {found})\n"
                  f"         -> config.JOURNALS 에 issn 을 직접 넣으세요", file=sys.stderr)
            continue

        issns = [i for i in best.get("ISSN", []) if i]
        if not issns:
            print(f"  [warn] ISSN 없음, 건너뜀: {name}", file=sys.stderr)
            continue

        cache[name] = {"title": best.get("title", name), "issns": issns}
        dirty = True
        resolved.append({"name": name, "title": best.get("title", name), "issns": issns})

    if dirty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return resolved


# ---------------------------------------------------------------------------
# 주제 분류
# ---------------------------------------------------------------------------
_ACRONYM_PATTERNS = {
    topic["key"]: [re.compile(rf"\b{re.escape(a)}\b") for a in topic.get("acronyms", [])]
    for topic in config.TOPICS
}

_EDITORIAL = re.compile(
    r"^\s*(?:" + "|".join(re.escape(p) for p in config.EXCLUDE_TITLE_PREFIXES) + r")\b",
    re.IGNORECASE,
)


def is_editorial(title: str) -> bool:
    """정정·논평·표지 등 논문이 아닌 항목인지 판정 (제목 앞부분으로만)."""
    return bool(_EDITORIAL.match(title or ""))


def match_topics(text: str) -> list[str]:
    """제목+초록+키워드 텍스트에서 해당하는 주제 key 목록을 뽑는다.

    판정 순서: (terms 부분 문자열 OR acronyms 단어 경계) AND context AND NOT exclude
    """
    lowered = text.lower()
    hits = []
    for topic in config.TOPICS:
        key = topic["key"]

        primary = (
            any(term.lower() in lowered for term in topic.get("terms", []))
            or any(pat.search(text) for pat in _ACRONYM_PATTERNS[key])
        )
        if not primary:
            continue

        context = topic.get("context")
        if context and not any(c.lower() in lowered for c in context):
            continue

        if any(e.lower() in lowered for e in topic.get("exclude", [])):
            continue

        hits.append(key)
    return hits


# ---------------------------------------------------------------------------
# Crossref 레코드 -> 내부 스키마
# ---------------------------------------------------------------------------
def clean_abstract(raw: str | None) -> str:
    """Crossref 초록은 JATS XML이다. 태그 제거 + 엔티티 복원 + 공백 정리."""
    if not raw:
        return ""
    text = _JATS_TAG.sub(" ", raw)
    text = html.unescape(text)
    text = _WS.sub(" ", text).strip()
    # 많은 출판사가 초록을 "Abstract" 라는 제목으로 시작한다
    return re.sub(r"^abstract[:\s]*", "", text, flags=re.IGNORECASE).strip()


def _parse_date_field(item: dict, field: str) -> tuple[str, str]:
    """Crossref 날짜 필드 -> (ISO 문자열, 정밀도).

    date-parts 는 [[2026, 8, 3]] 처럼 오지만 [[2026]] 만 오는 출판사도 있다
    (예: RSC). 빠진 자리는 1로 채우되 정밀도를 함께 돌려줘서, 호출 측이
    '2026-01-01' 을 진짜 1월 1일로 오해하지 않게 한다.
    """
    parts = item.get(field, {}).get("date-parts", [[]])
    if not parts or not parts[0] or not parts[0][0]:
        return "", ""
    raw = list(parts[0])
    precision = {1: "year", 2: "month"}.get(len(raw), "day")
    nums = (raw + [1, 1])[:3]
    try:
        return date(int(nums[0]), int(nums[1]), int(nums[2])).isoformat(), precision
    except (ValueError, TypeError):
        return "", ""


def _published(item: dict) -> tuple[str, str]:
    """출판일. 온라인 게재일 > 인쇄 게재일 > issued 순."""
    for field in ("published-online", "published-print", "issued"):
        iso, precision = _parse_date_field(item, field)
        if iso:
            return iso, precision
    return _parse_date_field(item, "created")


def _authors(item: dict) -> list[str]:
    names = []
    for a in item.get("author", []) or []:
        full = " ".join(p for p in (a.get("given"), a.get("family")) if p)
        names.append(full or a.get("name", ""))
    return [n for n in names if n]


def _first(value) -> str:
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def to_record(item: dict, journal_label: str) -> dict | None:
    """Crossref work -> 내부 레코드. 주제에 안 걸리면 None."""
    title = clean_text(_first(item.get("title")))
    if not title or is_editorial(title):
        return None

    abstract = clean_abstract(item.get("abstract"))
    subjects = " ".join(item.get("subject", []) or [])
    topics = match_topics(f"{title} {abstract} {subjects}")
    if not topics:
        return None

    doi = (item.get("DOI") or "").lower()
    published, precision = _published(item)
    created, _ = _parse_date_field(item, "created")
    return {
        "topics": topics,
        "title": title,
        "authors": _authors(item),
        "journal": clean_text(_first(item.get("container-title"))) or journal_label,
        "published": published,
        "published_precision": precision,   # "day" | "month" | "year"
        "created": created,                 # Crossref 최초 등록일 (항상 일 단위)
        "doi": doi,
        "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
        "abstract": abstract,
    }


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
_SELECT = ",".join([
    "DOI", "title", "author", "container-title", "issued",
    "published-online", "published-print", "created", "abstract", "URL", "subject",
])


def fetch_journal_works(
    session: requests.Session, issns: list[str], since: date, until: date
) -> list[dict]:
    """한 저널에서 [since, until] 사이에 **최초 등록**된 journal-article 전량.

    창의 기준을 created-date(Crossref 최초 등록일)로 잡는다. 후보였던 두 필드는
    각각 이렇게 실패했다:
      - index-date: 출판사가 과거 논문 메타데이터를 일괄 갱신하면 색인일이
        최신으로 바뀌어 수천 건이 딸려 온다 (실측: JACS 1주에 14,754건).
      - pub-date: RSC 등은 출판일을 연도 단위로만 등록해서 하한 필터에
        전부 걸려 나간다 (실측: EES 1주 2,066건 -> 0건).
    created-date 는 항상 일 단위이고 최초 등록 시점에만 찍히므로 둘 다 피한다.
    """
    filters = [f"issn:{i}" for i in issns]  # 같은 필터명 반복 = OR
    filters += [
        "type:journal-article",
        f"from-created-date:{since.isoformat()}",
        f"until-created-date:{until.isoformat()}",
    ]
    params = {
        "filter": ",".join(filters),
        "rows": config.CROSSREF_ROWS,
        "select": _SELECT,
        "cursor": "*",
    }

    items: list[dict] = []
    while True:
        data = _get(session, f"{config.CROSSREF_API}/works", params)
        message = data.get("message", {})
        batch = message.get("items", [])
        items.extend(batch)
        cursor = message.get("next-cursor")
        if not cursor or len(batch) < config.CROSSREF_ROWS:
            break
        params["cursor"] = cursor
        time.sleep(config.REQUEST_DELAY)  # 연속 요청 시 429가 실제로 발생한다
    return items


def collect(lookback_days: int = config.LOOKBACK_DAYS, *, today: date | None = None) -> list[dict]:
    """최근 lookback_days 일간 색인된 신규 논문을 수집해 레코드 리스트로 반환."""
    until = today or date.today()
    since = until - timedelta(days=lookback_days)
    oldest_allowed = until - timedelta(days=config.MAX_AGE_DAYS)

    session = _session()
    journals = resolve_journals(session)
    print(f"저널 {len(journals)}종, 등록 기간 {since} ~ {until}")

    records: list[dict] = []
    for journal in journals:
        try:
            items = fetch_journal_works(session, journal["issns"], since, until)
        except RuntimeError as exc:
            print(f"  [warn] {journal['name']}: {exc}", file=sys.stderr)
            continue

        matched = []
        for item in items:
            rec = to_record(item, journal["title"])
            if rec is None:
                continue
            # 최근 등록됐지만 실제로는 오래된 논문 제외.
            # 연도만 있는 출판일은 1월 1일로 해석되므로 이 판정에서 뺀다.
            if (rec["published_precision"] in ("day", "month")
                    and rec["published"] < oldest_allowed.isoformat()):
                continue
            matched.append(rec)

        print(f"  {journal['name']}: {len(items)}건 중 {len(matched)}건 매칭")
        records.extend(matched)

    return records


def _recency_key(rec: dict) -> str:
    """정렬용 최신도. 출판일이 연도 단위인 저널이 있어 created 를 우선 쓴다."""
    return rec.get("created") or rec.get("published") or ""


def cap_per_topic(records: list[dict], limit: int) -> list[dict]:
    """주제별 상한 적용. 최신순으로 자르고, 한 주제라도 살아남으면 레코드를 남긴다."""
    ordered = sorted(records, key=_recency_key, reverse=True)
    counts: dict[str, int] = {}
    kept = []
    for rec in ordered:
        surviving = [t for t in rec["topics"] if counts.get(t, 0) < limit]
        if not surviving:
            continue
        for t in surviving:
            counts[t] = counts.get(t, 0) + 1
        kept.append({**rec, "topics": surviving})
    return kept


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def topic_counts(records: list[dict]) -> dict[str, int]:
    """주제별 건수."""
    return {
        topic["key"]: sum(1 for r in records if topic["key"] in r["topics"])
        for topic in config.TOPICS
    }


def run(days: int = config.LOOKBACK_DAYS, *, archive: bool = True) -> tuple[list[dict], dict]:
    """수집 -> 중복 제거 -> 주제별 상한 -> (선택) 주차 아카이브 저장.

    반환값은 (레코드, 상한 적용 **전** 주제별 건수). 상한에 걸려 잘린 편수를
    대시보드에 표시하기 위해 필요하다 (조용한 절삭 방지).
    """
    from src.processors import dedupe

    records = collect(days)
    seen = dedupe.load_seen_dois(ROOT / config.PAPERS_DIR)
    fresh = dedupe.dedupe_papers(records, seen)
    totals = topic_counts(fresh)
    final = cap_per_topic(fresh, config.MAX_PAPERS_PER_TOPIC)
    shown = topic_counts(final)

    print(f"\n수집 {len(records)}건 -> 중복 제거 {len(fresh)}건 -> 상한 적용 {len(final)}건")
    for topic in config.TOPICS:
        key = topic["key"]
        cut = totals[key] - shown[key]
        note = f"  (상한으로 {cut}편 제외)" if cut else ""
        print(f"  {topic['label']}: {shown[key]}건{note}")

    if archive:
        today = date.today()
        year, week, _ = today.isocalendar()
        out = ROOT / config.PAPERS_DIR / f"{year}-W{week:02d}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "collected_at": today.isoformat(),
            "lookback_days": days,
            "count": len(final),
            "topic_totals": totals,
            "papers": final,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"저장: {out.relative_to(ROOT)}")

    return final, totals


def main() -> int:
    parser = argparse.ArgumentParser(description="논문 수집 (Crossref)")
    parser.add_argument("--days", type=int, default=config.LOOKBACK_DAYS,
                        help=f"조회 기간(일), 기본 {config.LOOKBACK_DAYS}")
    parser.add_argument("--no-archive", action="store_true",
                        help="파일로 저장하지 않고 결과만 출력")
    args = parser.parse_args()

    run(args.days, archive=not args.no_archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
