"""data/latest.json -> docs/index.html 렌더링.

Jinja2 템플릿(templates/dashboard.html.j2)을 쓴다. 스냅샷은 렌더링에 필요한
메타데이터(주제/기업 정의, 색)를 함께 담아 템플릿이 config 를 몰라도 되게 한다.

CLI:
    python -m src.render                  # data/latest.json -> docs/index.html
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone  # noqa: F401 (date: days_until)
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import config

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=config.KST_OFFSET_HOURS))


# ---------------------------------------------------------------------------
# 스냅샷
# ---------------------------------------------------------------------------
def build_snapshot(
    papers: list[dict],
    news: list[dict],
    jobs: list[dict] | None = None,
    *,
    lookback_days: int = config.LOOKBACK_DAYS,
    topic_totals: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """수집 결과를 대시보드가 읽는 단일 스냅샷으로 묶는다.

    topic_totals 는 주제별 상한을 적용하기 **전** 건수다. 상한에 걸려 잘린
    편수를 대시보드가 밝힐 수 있게 함께 저장한다.
    """
    stamp = now or datetime.now(KST)
    year, week, _ = stamp.date().isocalendar()

    return {
        "generated_at": stamp.isoformat(timespec="minutes"),
        "week": f"{year}-W{week:02d}",
        "lookback_days": lookback_days,
        "topic_totals": topic_totals or {},
        "journal_count": len(config.JOURNALS),
        "topics": [
            {k: t[k] for k in ("key", "label", "color", "color_dark")}
            for t in config.TOPICS
        ],
        "companies": [
            {k: c[k] for k in ("key", "label")}
            for c in config.COMPANIES
        ],
        "job_companies": [
            {k: c[k] for k in ("key", "label")}
            for c in config.JOB_COMPANIES
        ],
        "deadline_soon_days": config.JOB_DEADLINE_SOON_DAYS,
        "today": stamp.date().isoformat(),
        "papers": papers,
        "news": news,
        "jobs": jobs or [],
    }


def write_snapshot(snapshot: dict, path: Path | str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# 그룹핑 (템플릿 입력)
# ---------------------------------------------------------------------------
def _recency(rec: dict) -> str:
    return rec.get("created") or rec.get("published_at") or rec.get("published") or ""


def group_papers(snapshot: dict) -> list[dict]:
    """주제별 섹션. 한 논문이 여러 주제에 걸리면 각 섹션에 모두 들어간다."""
    sections = []
    for topic in snapshot["topics"]:
        source = [p for p in snapshot["papers"] if topic["key"] in p.get("topics", [])]
        source.sort(key=_recency, reverse=True)
        # 한 논문이 여러 섹션에 들어가므로 섹션마다 복사본을 만든다. 원본을 그대로
        # 수정하면 also_in 이 마지막으로 처리된 섹션 기준으로 덮어써진다.
        items = [
            {
                **paper,
                # 다른 주제는 색이 아니라 글자로만 표시한다 (한 섹션에 한 색 원칙)
                "also_in": [
                    t["label"] for t in snapshot["topics"]
                    if t["key"] in paper.get("topics", []) and t["key"] != topic["key"]
                ],
            }
            for paper in source
        ]
        # 키 이름을 'items' 로 두면 Jinja 가 dict.items() 메서드로 해석해 버린다
        total = snapshot.get("topic_totals", {}).get(topic["key"], len(items))
        sections.append({
            **topic,
            "count": len(items),
            "total": total,
            "truncated": max(0, total - len(items)),
            "entries": items,
        })
    return sections


def group_news(snapshot: dict) -> list[dict]:
    """기업별 섹션."""
    labels = {c["key"]: c["label"] for c in snapshot["companies"]}
    sections = []
    for company in snapshot["companies"]:
        source = [n for n in snapshot["news"] if company["key"] in n.get("companies", [])]
        source.sort(key=_recency, reverse=True)
        # 논문과 같은 이유로 복사본을 만든다 (한 기사가 여러 기업 섹션에 들어간다)
        items = [
            {
                **article,
                "also_in": [
                    labels[k] for k in article.get("companies", [])
                    if k != company["key"] and k in labels
                ],
            }
            for article in source
        ]
        sections.append({**company, "count": len(items), "entries": items})
    return sections


def group_jobs(snapshot: dict) -> list[dict]:
    """기업별 채용 섹션. 마감 임박 순으로 정렬한다.

    논문·뉴스와 달리 정렬 기준이 '최신' 이 아니라 '마감 임박' 이다.
    지원 마감이 가까운 공고를 놓치는 게 가장 큰 손해이기 때문이다.
    """
    labels = {c["key"]: c["label"] for c in snapshot.get("job_companies", [])}
    today = snapshot.get("today", "")
    soon = snapshot.get("deadline_soon_days", config.JOB_DEADLINE_SOON_DAYS)

    def sort_key(job: dict) -> tuple[int, str]:
        return (0, job["deadline"]) if job.get("deadline") else (1, job.get("posted", ""))

    sections = []
    for company in snapshot.get("job_companies", []):
        source = [j for j in snapshot.get("jobs", [])
                  if company["key"] in j.get("companies", [])]
        source.sort(key=sort_key)

        items = []
        for job in source:
            items.append({
                **job,
                "days_left": days_until(job.get("deadline", ""), today),
                "closing_soon": 0 <= (days_until(job.get("deadline", ""), today) or 999) <= soon,
                "also_in": [labels[k] for k in job.get("companies", [])
                            if k != company["key"] and k in labels],
            })
        sections.append({**company, "count": len(items), "entries": items})
    return sections


def days_until(deadline: str, today: str) -> int | None:
    """마감까지 남은 일수. 마감일이 없거나 형식이 이상하면 None."""
    if not deadline or not today:
        return None
    try:
        end = date.fromisoformat(deadline)
        start = date.fromisoformat(today)
    except ValueError:
        return None
    return (end - start).days


def format_deadline(job: dict) -> str:
    """'D-3' / '오늘 마감' / '상시채용' 형태로."""
    if not job.get("deadline"):
        return job.get("close_type") or "상시채용"
    left = job.get("days_left")
    if left is None:
        return job["deadline"]
    if left < 0:
        return "마감"
    if left == 0:
        return "오늘 마감"
    return f"D-{left}"


def format_published(paper: dict) -> str:
    """출판일 표시. 연도만 등록된 저널은 '2026년'처럼 정밀도에 맞춰 줄인다."""
    published, precision = paper.get("published", ""), paper.get("published_precision")
    if not published:
        return ""
    if precision == "year":
        return f"{published[:4]}년"
    if precision == "month":
        return f"{published[:4]}.{published[5:7]}"
    return published


# ---------------------------------------------------------------------------
# 렌더링
# ---------------------------------------------------------------------------
def render(
    snapshot_path: str | Path = None,
    template_path: str | Path = None,
    output_path: str | Path = None,
) -> Path:
    snapshot_path = Path(snapshot_path or ROOT / config.LATEST_SNAPSHOT)
    template_path = Path(template_path or ROOT / config.TEMPLATE)
    output_path = Path(output_path or ROOT / config.OUTPUT_HTML)

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    env = Environment(
        loader=FileSystemLoader(template_path.parent),
        autoescape=select_autoescape(["html", "xml", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["published"] = format_published
    env.filters["deadline"] = format_deadline
    template = env.get_template(template_path.name)

    paper_sections = group_papers(snapshot)
    news_sections = group_news(snapshot)
    job_sections = group_jobs(snapshot)

    html = template.render(
        snapshot=snapshot,
        paper_sections=paper_sections,
        news_sections=news_sections,
        job_sections=job_sections,
        paper_total=len(snapshot["papers"]),
        news_total=len(snapshot["news"]),
        job_total=len(snapshot.get("jobs", [])),
        job_new_total=sum(1 for j in snapshot.get("jobs", []) if j.get("is_new")),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="대시보드 렌더링")
    parser.add_argument("--snapshot", default=None, help="기본 data/latest.json")
    parser.add_argument("--output", default=None, help="기본 docs/index.html")
    args = parser.parse_args()

    out = render(snapshot_path=args.snapshot, output_path=args.output)
    print(f"렌더링 완료: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
