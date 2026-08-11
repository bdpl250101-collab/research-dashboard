"""렌더링 오프라인 테스트 (네트워크 없이 스냅샷 구성·그룹핑·HTML 생성 검증).

    pytest tests/            또는            python tests/test_render.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, render  # noqa: E402

KST = timezone(timedelta(hours=9))

PAPER = {
    "topics": ["electrocatalysis", "oer_her"],
    "title": "A dual-interlocked electrocatalyst for water electrolysis",
    "authors": ["Jane Doe", "John Roe", "Kim Park", "Lee Choi"],
    "journal": "ACS Catalysis",
    "published": "2026-08-10",
    "published_precision": "day",
    "created": "2026-08-10",
    "doi": "10.1/abc",
    "url": "https://doi.org/10.1/abc",
    "abstract": "We report a durable catalyst.",
}

NEWS = {
    "companies": ["posco"],
    "title": "포스코, 신규 설비 투자",
    "source": "연합뉴스",
    "published": "2026-08-11",
    "published_at": "2026-08-11T09:00:00+09:00",
    "url": "https://news.google.com/x",
    "summary": "",
    "title_match": True,
    "window_days": 7,
}


def _snapshot():
    return render.build_snapshot(
        [PAPER], [NEWS], lookback_days=7,
        now=datetime(2026, 8, 11, 15, 0, tzinfo=KST),
    )


def test_snapshot_has_week_and_metadata():
    snap = _snapshot()
    assert snap["week"] == "2026-W33"
    assert snap["generated_at"].startswith("2026-08-11T15:00")
    assert len(snap["topics"]) == len(config.TOPICS)
    assert len(snap["companies"]) == len(config.COMPANIES)
    # 템플릿이 config 를 몰라도 되도록 색까지 스냅샷에 들어간다
    assert all("color" in t and "color_dark" in t for t in snap["topics"])


def test_paper_appears_in_every_matching_topic_section():
    sections = render.group_papers(_snapshot())
    by_key = {s["key"]: s for s in sections}
    assert by_key["electrocatalysis"]["count"] == 1
    assert by_key["oer_her"]["count"] == 1
    assert by_key["pfas"]["count"] == 0
    # 다른 주제는 색이 아니라 글자로만 표시된다. 섹션마다 관점이 달라야 하므로
    # 한 논문이 두 섹션에 들어가도 서로 다른 also_in 을 가져야 한다.
    assert by_key["electrocatalysis"]["entries"][0]["also_in"] == ["OER / HER"]
    assert by_key["oer_her"]["entries"][0]["also_in"] == ["전기화학 촉매"]


def test_multi_company_news_gets_per_section_labels():
    snap = render.build_snapshot(
        [], [{**NEWS, "companies": ["posco", "samsung_sdi"]}],
        lookback_days=7, now=datetime(2026, 8, 11, tzinfo=KST),
    )
    by_key = {s["key"]: s for s in render.group_news(snap)}
    assert by_key["posco"]["entries"][0]["also_in"] == ["삼성SDI"]
    assert by_key["samsung_sdi"]["entries"][0]["also_in"] == ["POSCO홀딩스"]


def test_truncated_topics_report_the_real_total():
    # 상한에 걸려 잘린 편수는 조용히 사라지면 안 된다
    snap = render.build_snapshot(
        [PAPER], [], lookback_days=7,
        topic_totals={"electrocatalysis": 66, "oer_her": 1, "pfas": 0, "organocatalysis": 0},
        now=datetime(2026, 8, 11, tzinfo=KST),
    )
    by_key = {s["key"]: s for s in render.group_papers(snap)}
    assert by_key["electrocatalysis"]["total"] == 66
    assert by_key["electrocatalysis"]["truncated"] == 65
    assert by_key["oer_her"]["truncated"] == 0

    with tempfile.TemporaryDirectory() as tmp:
        path = render.write_snapshot(snap, Path(tmp) / "latest.json")
        html = render.render(snapshot_path=path,
                             output_path=Path(tmp) / "index.html").read_text(encoding="utf-8")
    assert "총 66편 중 1편" in html


def test_missing_topic_totals_falls_back_to_shown_count():
    # 예전 형식 스냅샷(topic_totals 없음)도 렌더링돼야 한다
    snap = _snapshot()
    snap.pop("topic_totals", None)
    by_key = {s["key"]: s for s in render.group_papers(snap)}
    assert by_key["electrocatalysis"]["total"] == 1
    assert by_key["electrocatalysis"]["truncated"] == 0


def test_sections_use_entries_key_not_items():
    # 'items' 로 두면 Jinja 가 dict.items() 메서드로 해석해 렌더링이 깨진다
    section = render.group_papers(_snapshot())[0]
    assert "entries" in section and "items" not in section


def test_topic_colors_follow_validated_slot_order():
    # 순서 자체가 색각 이상 안전장치다. 색을 바꾸면 검증기를 다시 돌려야 한다.
    # (현재 값: 인접 배치 최악 CVD ΔE 17.1 로 라이트/다크 모두 통과)
    assert [t["color"] for t in config.TOPICS] == \
        ["#219761", "#3a84ca", "#be6438", "#866ec5"]
    assert [t["color_dark"] for t in config.TOPICS] == \
        ["#2a9d67", "#418ad1", "#c56a3e", "#8c74cc"]


def test_format_published_respects_precision():
    assert render.format_published({"published": "2026-08-10", "published_precision": "day"}) \
        == "2026-08-10"
    assert render.format_published({"published": "2026-08-01", "published_precision": "month"}) \
        == "2026.08"
    assert render.format_published({"published": "2026-01-01", "published_precision": "year"}) \
        == "2026년"
    assert render.format_published({"published": ""}) == ""


def test_render_produces_html_with_content():
    snap = _snapshot()
    with tempfile.TemporaryDirectory() as tmp:
        snapshot_path = render.write_snapshot(snap, Path(tmp) / "latest.json")
        out = render.render(snapshot_path=snapshot_path, output_path=Path(tmp) / "index.html")
        html = out.read_text(encoding="utf-8")

    assert "<!doctype html>" in html
    assert 'lang="ko"' in html
    assert "2026-W33" in html
    assert PAPER["title"] in html
    assert NEWS["title"] in html
    assert "연합뉴스" in html
    # 저자는 3명까지 + 나머지 인원수
    assert "외 1명" in html
    # 주제 색이 섹션 인라인 변수로 주입된다
    assert "--topic-light: #219761" in html
    # 외부 링크는 새 탭 + noopener
    assert 'rel="noopener"' in html


def test_render_escapes_html_in_titles():
    snap = render.build_snapshot(
        [{**PAPER, "title": "<script>alert(1)</script> catalysis"}], [],
        lookback_days=7, now=datetime(2026, 8, 11, tzinfo=KST),
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = render.write_snapshot(snap, Path(tmp) / "latest.json")
        html = render.render(snapshot_path=path,
                             output_path=Path(tmp) / "index.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_handles_empty_snapshot():
    snap = render.build_snapshot([], [], lookback_days=7,
                                 now=datetime(2026, 8, 11, tzinfo=KST))
    with tempfile.TemporaryDirectory() as tmp:
        path = render.write_snapshot(snap, Path(tmp) / "latest.json")
        html = render.render(snapshot_path=path,
                             output_path=Path(tmp) / "index.html").read_text(encoding="utf-8")
    # 수집이 0건이어도 페이지는 나와야 한다
    assert "이번 주 신규 논문이 없습니다." in html
    assert "이번 주 신규 소식이 없습니다." in html


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print("실패 없음" if not failures else f"{failures}건 실패")
    raise SystemExit(1 if failures else 0)
