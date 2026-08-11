"""뉴스 수집기 오프라인 테스트 (네트워크 없이 정제·순위·중복 제거만 검증).

    pytest tests/            또는            python tests/test_news.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collectors import news  # noqa: E402
from src.processors import dedupe  # noqa: E402


def _entry(title, source="연합뉴스", published=(2026, 8, 7, 9, 43, 0), link="https://x/1"):
    return {
        "title": f"{title} - {source}",
        "source": {"title": source},
        "published_parsed": time.struct_time(published + (0, 0, 0)),
        "link": link,
        "summary": f'<a href="{link}">{title}</a>',
    }


def test_source_suffix_is_stripped():
    rec = news.to_record(_entry("삼성SDI, GM과 배터리 합작 종료"), "samsung_sdi", ["삼성SDI"])
    assert rec["title"] == "삼성SDI, GM과 배터리 합작 종료"
    assert rec["source"] == "연합뉴스"


def test_gmt_is_converted_to_kst():
    # GMT 22:30 = KST 다음날 07:30. 변환 안 하면 날짜가 하루 밀린다.
    rec = news.to_record(_entry("포스코 리튬 투자", published=(2026, 8, 10, 22, 30, 0)),
                         "posco", ["포스코"])
    assert rec["published"] == "2026-08-11"
    assert rec["published_at"].startswith("2026-08-11T07:30")


def test_summary_is_dropped_when_it_is_just_the_link():
    rec = news.to_record(_entry("GS칼텍스 신사업"), "gscaltex", ["GS칼텍스"])
    assert rec["summary"] == ""


def test_title_match_flag():
    titled = news.to_record(_entry("조선내화, 신규 설비 투자"), "chosun", ["조선내화"])
    body = news.to_record(_entry("광양시, 폭염 대응 클린로드 운영"), "chosun", ["조선내화"])
    assert titled["title_match"] is True
    assert body["title_match"] is False


def test_market_noise_is_dropped():
    assert news.is_market_noise("OCI홀딩스 주가, 8월 11일 장중 274,500원 3.51% 하락")
    assert news.is_market_noise("조선내화 투자분석 2026. 08. 07")
    assert not news.is_market_noise("OCI홀딩스, 텍사스 셀 공장 재추진 저울질")
    assert news.to_record(_entry("OCI홀딩스 주가 급락"), "oci", ["OCI홀딩스"]) is None


def test_rank_prefers_title_match_and_caps_body_only():
    records = (
        [{"title_match": True, "published_at": f"2026-08-0{i}"} for i in range(1, 4)]
        + [{"title_match": False, "published_at": f"2026-08-1{i}"} for i in range(1, 6)]
    )
    picked = news.rank_and_cap(records, limit=5, body_only_limit=2)
    assert sum(1 for r in picked if r["title_match"]) == 3
    assert sum(1 for r in picked if not r["title_match"]) == 2   # 본문 언급 상한
    # 본문 언급 기사가 더 최신이어도 제목 매칭이 앞선다
    assert picked[0]["title_match"] is True


def test_body_only_does_not_displace_title_matches():
    records = [{"title_match": True, "published_at": f"2026-08-0{i}"} for i in range(1, 7)]
    picked = news.rank_and_cap(records, limit=5, body_only_limit=2)
    assert len(picked) == 5
    assert all(r["title_match"] for r in picked)


def test_merge_duplicates_unions_companies():
    records = [
        {"title": "삼성SDI·SK온 전고체 상용화", "url": "https://a", "companies": ["samsung_sdi"],
         "title_match": True},
        {"title": "삼성SDI·SK온 전고체 상용화", "url": "https://b", "companies": ["sk_on"],
         "title_match": False},
    ]
    merged = news.merge_duplicates(records)
    assert len(merged) == 1
    assert merged[0]["companies"] == ["samsung_sdi", "sk_on"]
    assert merged[0]["title_match"] is True


def test_dedupe_news_matches_on_title_or_url():
    seen = {dedupe.normalize_url("https://news.google.com/old")}
    records = [
        {"title": "새 기사", "url": "https://news.google.com/new", "companies": ["posco"]},
        {"title": "이전 기사", "url": "https://news.google.com/old", "companies": ["posco"]},
        {"title": "새 기사", "url": "https://news.google.com/other", "companies": ["posco"]},
    ]
    fresh = dedupe.dedupe_news(records, seen)
    assert [r["url"] for r in fresh] == ["https://news.google.com/new"]


def test_build_query_ors_aliases():
    q = news.build_query({"aliases": ["린데코리아", "Linde Korea"]}, 7)
    assert q == '("린데코리아" OR "Linde Korea") when:7d'


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
