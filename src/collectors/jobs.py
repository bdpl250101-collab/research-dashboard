"""채용공고 수집기 (사람인 오픈 API).

동작 방식
---------
1. 기업별로 대표 별칭을 keywords 로 넘겨 조회한다 (기업당 1회 호출).
2. 사람인의 keywords 는 회사명뿐 아니라 공고 제목·업종·본문까지 훑기 때문에
   다른 회사 공고가 섞여 온다. 회사명(company.detail.name)이 별칭과 맞는
   공고만 남긴다.
3. 마감된 공고(active=0, 마감일 경과)는 버린다.
4. 마감 임박 순으로 정렬해 기업당 상한만큼 남긴다.

논문·뉴스와 다른 점
-------------------
논문·뉴스는 '이번 주 신규' 가 핵심이라 지난 주차와 대조해 중복을 제거한다.
채용공고는 '지금 지원할 수 있는가' 가 핵심이므로 **이전 주에 이미 본 공고도
마감 전이면 계속 보여준다**. 대신 직전 주차에 없던 공고에 신규 표시를 단다.

레코드 스키마:
    {
        "companies": list[str],   # config.JOB_COMPANIES 의 key
        "title": str,             # 공고 제목
        "company_name": str,      # 실제 등록 회사명 (계열사 구분용)
        "url": str,
        "posted": str,            # 등록일 YYYY-MM-DD (KST)
        "deadline": str,          # 마감일 YYYY-MM-DD (KST), 상시채용이면 ""
        "close_type": str,        # 접수마감일 / 상시채용 등
        "location": str,
        "job_type": str,          # 정규직 / 계약직 …
        "experience": str,        # 경력무관 / 신입 …
        "education": str,
        "industry": str,
        "job_id": str,            # 사람인 공고 번호 (중복 판정 키)
        "is_new": bool,           # 직전 주차 아카이브에 없던 공고
    }

CLI:
    SARAMIN_API_KEY=... python -m src.collectors.jobs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from src import config
from src.text import clean_text

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=config.KST_OFFSET_HOURS))


class MissingKey(RuntimeError):
    """SARAMIN_API_KEY 가 없을 때. 채용 수집만 건너뛰고 나머지는 진행한다."""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def api_key() -> str:
    key = os.environ.get("SARAMIN_API_KEY", "").strip()
    if not key:
        raise MissingKey(
            "SARAMIN_API_KEY 가 설정되지 않았습니다. "
            "https://oapi.saramin.co.kr 에서 무료 발급 후 환경변수로 넣으세요."
        )
    return key


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json",
                      "User-Agent": "research-dashboard/0.1"})
    return s


def fetch_company(session: requests.Session, key: str, keyword: str) -> list[dict]:
    """한 기업의 공고 목록. 실패하면 빈 리스트."""
    params = {
        "access-key": key,
        "keywords": keyword,
        "count": config.SARAMIN_COUNT,
        "start": 0,
        "sort": "pd",                               # 등록일 최신순
        "fields": "posting-date,expiration-date",
    }
    for attempt in range(config.MAX_RETRIES):
        try:
            resp = session.get(config.SARAMIN_API, params=params,
                               timeout=config.REQUEST_TIMEOUT)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            if attempt == config.MAX_RETRIES - 1:
                print(f"  [warn] '{keyword}' 조회 실패: {exc}", file=sys.stderr)
                return []
            time.sleep(2 ** attempt)
            continue

        # 오류는 {"code":1,"message":"..."} 형태로 온다 (HTTP 200 이어도)
        if "code" in data and "jobs" not in data:
            message = data.get("message", "")
            if str(data.get("code")) == "4":
                raise RuntimeError(f"사람인 일일 호출 한도 초과: {message}")
            raise RuntimeError(f"사람인 API 오류 {data.get('code')}: {message}")

        return data.get("jobs", {}).get("job", []) or []
    return []


# ---------------------------------------------------------------------------
# 회사명 대조
# ---------------------------------------------------------------------------
_LATIN_SHORT = re.compile(r"^[A-Za-z0-9\-]{1,4}$")


def _alias_pattern(alias: str) -> re.Pattern | None:
    """짧은 라틴 별칭만 경계 조건을 건다.

    'LS' 를 그냥 부분 문자열로 찾으면 TOOLS 같은 이름에 걸린다. 반대로 \\b 는
    한글이 단어 문자로 취급돼 'LS전선' 에서 경계가 생기지 않아 못 쓴다.
    그래서 앞뒤에 라틴 문자·숫자가 오지 않는 경우만 인정한다.
    """
    if not _LATIN_SHORT.match(alias):
        return None
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
                      re.IGNORECASE)


def company_matches(name: str, aliases: list[str]) -> bool:
    """등록 회사명이 이 기업(그룹)의 것인지."""
    if not name:
        return False
    lowered = name.lower()
    for alias in aliases:
        pattern = _alias_pattern(alias)
        if pattern is not None:
            if pattern.search(name):
                return True
        elif alias.lower() in lowered:
            return True
    return False


# ---------------------------------------------------------------------------
# 레코드 변환
# ---------------------------------------------------------------------------
def _nested(item: dict, *path: str) -> str:
    node = item
    for step in path:
        if not isinstance(node, dict):
            return ""
        node = node.get(step)
    return clean_text(node) if isinstance(node, str) else ""


def _iso_date(value: str) -> str:
    """'2026-08-11T13:46:04+0900' 또는 timestamp -> KST 기준 YYYY-MM-DD."""
    if not value:
        return ""
    text = str(value).strip()
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), KST).date().isoformat()
        except (ValueError, OSError):
            return ""
    try:
        return datetime.fromisoformat(text).astimezone(KST).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else ""


def to_record(item: dict, company_key: str, aliases: list[str]) -> dict | None:
    """사람인 job -> 내부 레코드. 다른 회사 공고면 None."""
    name = _nested(item, "company", "detail", "name")
    if not company_matches(name, aliases):
        return None

    title = _nested(item, "position", "title")
    if not title:
        return None

    return {
        "companies": [company_key],
        "title": title,
        "company_name": name,
        "url": item.get("url", "") or _nested(item, "company", "detail", "href"),
        "posted": _iso_date(item.get("posting-date") or item.get("posting-timestamp", "")),
        "deadline": _iso_date(item.get("expiration-date")
                              or item.get("expiration-timestamp", "")),
        "close_type": _nested(item, "close-type", "name"),
        "location": _nested(item, "position", "location", "name"),
        "job_type": _nested(item, "position", "job-type", "name"),
        "experience": _nested(item, "position", "experience-level", "name"),
        "education": _nested(item, "position", "required-education-level", "name"),
        "industry": _nested(item, "position", "industry", "name"),
        "job_id": str(item.get("id", "")),
        "is_new": False,          # collect() 에서 직전 주차와 대조해 채운다
    }


def is_open(record: dict, today: date) -> bool:
    """아직 지원 가능한 공고인지. 마감일이 없으면(상시채용) 열린 것으로 본다."""
    deadline = record.get("deadline")
    if not deadline:
        return True
    return deadline >= today.isoformat()


def _deadline_key(record: dict) -> tuple[int, str]:
    """마감 임박 순. 마감일 없는 상시채용은 뒤로 보낸다."""
    deadline = record.get("deadline")
    return (0, deadline) if deadline else (1, record.get("posted", ""))


def cap_per_company(records: list[dict], limit: int) -> list[dict]:
    return sorted(records, key=_deadline_key)[:limit]


def merge_duplicates(records: list[dict]) -> list[dict]:
    """같은 공고가 여러 기업 키워드에 걸린 경우 companies 를 합친다."""
    merged: dict[str, dict] = {}
    for rec in records:
        key = rec["job_id"] or f"{rec['company_name']}|{rec['title']}"
        if key in merged:
            for company in rec["companies"]:
                if company not in merged[key]["companies"]:
                    merged[key]["companies"].append(company)
        else:
            merged[key] = {**rec, "companies": list(rec["companies"])}
    return list(merged.values())


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def collect(*, today: date | None = None, previous_ids: set[str] | None = None) -> list[dict]:
    """기업별 진행 중인 공고를 수집한다."""
    today = today or date.today()
    previous_ids = previous_ids or set()
    key = api_key()
    session = _session()

    collected: list[dict] = []
    for company in config.JOB_COMPANIES:
        items = fetch_company(session, key, company["aliases"][0])

        records = []
        for item in items:
            if str(item.get("active", "1")) == "0":
                continue
            rec = to_record(item, company["key"], company["aliases"])
            if rec and is_open(rec, today):
                rec["is_new"] = rec["job_id"] not in previous_ids
                records.append(rec)

        picked = cap_per_company(records, config.MAX_JOBS_PER_COMPANY)
        dropped = len(records) - len(picked)
        note = f" (상한으로 {dropped}건 제외)" if dropped > 0 else ""
        print(f"  {company['label']}: {len(items)}건 중 {len(picked)}건{note}")
        collected.extend(picked)

        time.sleep(config.REQUEST_DELAY)

    return merge_duplicates(collected)


def run(*, archive: bool = True) -> list[dict]:
    """수집 -> (선택) 주차 아카이브 저장. 키가 없으면 MissingKey 를 올린다."""
    from src.processors import dedupe

    today = date.today()
    current = dedupe.archive_name(today)
    previous_ids = dedupe.load_seen_job_ids(ROOT / config.JOBS_DIR, exclude=current)

    print(f"기업 {len(config.JOB_COMPANIES)}곳")
    records = collect(today=today, previous_ids=previous_ids)

    new_count = sum(1 for r in records if r["is_new"])
    print(f"\n진행 중인 공고 {len(records)}건 (신규 {new_count}건)")

    if archive:
        out = ROOT / config.JOBS_DIR / current
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "collected_at": today.isoformat(),
            "count": len(records),
            "jobs": records,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"저장: {out.relative_to(ROOT)}")

    return records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="채용공고 수집 (사람인 오픈 API)")
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()

    try:
        run(archive=not args.no_archive)
    except MissingKey as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
