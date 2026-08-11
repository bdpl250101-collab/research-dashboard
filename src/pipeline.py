"""주간 파이프라인: 수집 -> 스냅샷 -> 대시보드 렌더링.

GitHub Actions 가 매주 실행하는 진입점이다.

    python -m src.pipeline                 # 전체 실행
    python -m src.pipeline --days 14       # 조회 기간 변경
    python -m src.pipeline --skip-news     # 논문만 다시 수집
    python -m src.pipeline --render-only   # 수집 없이 latest.json 으로 다시 렌더링

수집 단계가 실패해도 나머지는 진행한다. 한 소스가 죽었다고 대시보드 전체가
빈 페이지로 배포되면 안 되기 때문이다. 실패한 소스는 직전 스냅샷 값을 재사용한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from src import config, render
from src.collectors import news as news_collector
from src.collectors import papers as papers_collector

ROOT = Path(__file__).resolve().parents[1]


def _previous_snapshot() -> dict:
    path = ROOT / config.LATEST_SNAPSHOT
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _latest_archive(directory: Path, key: str) -> list[dict]:
    """가장 최근 주차 아카이브에서 레코드를 읽는다 (스냅샷 재구성용)."""
    files = sorted(directory.glob("*.json"))
    if not files:
        return []
    try:
        return json.loads(files[-1].read_text(encoding="utf-8")).get(key, [])
    except (json.JSONDecodeError, OSError):
        return []


def _safe(label: str, fn, fallback: list[dict]) -> tuple[list[dict], bool]:
    """수집 함수를 실행하되, 실패하면 직전 값으로 대체하고 계속 진행한다."""
    try:
        return fn(), True
    except Exception:                                  # noqa: BLE001 - 어떤 실패든 페이지는 살린다
        print(f"\n[error] {label} 수집 실패 — 직전 스냅샷 {len(fallback)}건을 유지합니다",
              file=sys.stderr)
        traceback.print_exc()
        return fallback, False


def main() -> int:
    parser = argparse.ArgumentParser(description="주간 수집 + 대시보드 생성")
    parser.add_argument("--days", type=int, default=config.LOOKBACK_DAYS)
    parser.add_argument("--skip-papers", action="store_true")
    parser.add_argument("--skip-news", action="store_true")
    parser.add_argument("--render-only", action="store_true",
                        help="수집 없이 기존 latest.json 으로 렌더링만")
    parser.add_argument("--from-archive", action="store_true",
                        help="수집 없이 최신 주차 아카이브로 스냅샷을 다시 만들고 렌더링")
    parser.add_argument("--no-archive", action="store_true",
                        help="주차 아카이브를 저장하지 않음")
    args = parser.parse_args()

    if args.render_only:
        out = render.render()
        print(f"렌더링 완료: {out.relative_to(ROOT)}")
        return 0

    if args.from_archive:
        papers = _latest_archive(ROOT / config.PAPERS_DIR, "papers")
        news = _latest_archive(ROOT / config.NEWS_DIR, "news")
        totals = _latest_archive(ROOT / config.PAPERS_DIR, "topic_totals") or {}
        snapshot = render.build_snapshot(papers, news, lookback_days=args.days,
                                         topic_totals=totals)
        path = render.write_snapshot(snapshot, ROOT / config.LATEST_SNAPSHOT)
        out = render.render(snapshot_path=path)
        print(f"아카이브에서 재구성: 논문 {len(papers)}편 / 뉴스 {len(news)}건")
        print(f"렌더링 완료: {out.relative_to(ROOT)}")
        return 0

    previous = _previous_snapshot()
    archive = not args.no_archive
    ok = True

    print("=" * 60)
    print("논문 수집")
    print("=" * 60)
    if args.skip_papers:
        papers = previous.get("papers", [])
        totals = previous.get("topic_totals", {})
        print(f"건너뜀 — 직전 {len(papers)}편 유지")
    else:
        # papers.run 은 (레코드, 상한 적용 전 주제별 건수) 를 돌려준다
        (papers, totals), good = _safe(
            "논문",
            lambda: papers_collector.run(args.days, archive=archive),
            (previous.get("papers", []), previous.get("topic_totals", {})),
        )
        ok = ok and good

    print("\n" + "=" * 60)
    print("기업 뉴스 수집")
    print("=" * 60)
    if args.skip_news:
        news = previous.get("news", [])
        print(f"건너뜀 — 직전 {len(news)}건 유지")
    else:
        news, good = _safe(
            "뉴스",
            lambda: news_collector.run(args.days, archive=archive),
            previous.get("news", []),
        )
        ok = ok and good

    snapshot = render.build_snapshot(papers, news, lookback_days=args.days,
                                     topic_totals=totals)
    snapshot_path = render.write_snapshot(snapshot, ROOT / config.LATEST_SNAPSHOT)
    output = render.render(snapshot_path=snapshot_path)

    print("\n" + "=" * 60)
    print(f"스냅샷: {snapshot_path.relative_to(ROOT)}  (논문 {len(papers)}편 / 뉴스 {len(news)}건)")
    print(f"대시보드: {output.relative_to(ROOT)}")
    if not ok:
        print("일부 소스 수집에 실패했습니다 (위 로그 참고). 페이지는 생성되었습니다.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
