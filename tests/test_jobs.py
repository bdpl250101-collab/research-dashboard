"""채용공고 수집기 오프라인 테스트 (네트워크·API 키 없이 변환·정렬·대조 검증).

    pytest tests/            또는            python tests/test_jobs.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import render  # noqa: E402
from src.collectors import jobs  # noqa: E402

# 사람인 API 응답 형태 그대로
RAW = {
    "url": "https://www.saramin.co.kr/job/1",
    "active": 1,
    "company": {"detail": {"href": "https://x", "name": "한화솔루션(주)"}},
    "position": {
        "title": "촉매 연구개발 경력사원 모집",
        "industry": {"code": "1", "name": "석유화학"},
        "location": {"code": "1", "name": "서울 중구"},
        "job-type": {"code": "1", "name": "정규직"},
        "experience-level": {"code": 2, "min": 3, "max": 7, "name": "경력 3~7년"},
        "required-education-level": {"code": "8", "name": "대학교졸업(4년)이상"},
    },
    "salary": {"code": "0", "name": "회사내규에 따름"},
    "id": "50001",
    "posting-date": "2026-08-10T09:00:00+0900",
    "expiration-date": "2026-08-20T23:59:59+0900",
    "close-type": {"code": "1", "name": "접수마감일"},
}


def test_company_matches_group_wide():
    # 그룹명을 넣으면 계열사가 모두 걸린다
    assert jobs.company_matches("한화솔루션(주)", ["한화"])
    assert jobs.company_matches("한화에어로스페이스", ["한화"])
    assert not jobs.company_matches("삼성전자", ["한화"])


def test_short_latin_alias_needs_boundary():
    """'LS' 를 부분 문자열로 찾으면 엉뚱한 회사가 걸린다."""
    assert jobs.company_matches("LS전선", ["LS"])          # 한글이 뒤에 붙는 건 정상
    assert jobs.company_matches("LS일렉트릭(주)", ["LS"])
    assert not jobs.company_matches("TOOLS코리아", ["LS"])  # 라틴 문자에 둘러싸이면 제외
    assert not jobs.company_matches("FALSE컴퍼니", ["LS"])


def test_e1_and_sk_aliases():
    assert jobs.company_matches("E1(주)", ["E1"])
    assert not jobs.company_matches("PIPE1솔루션", ["E1"])
    assert jobs.company_matches("SK이노베이션", ["SK", "에스케이"])
    assert not jobs.company_matches("DUSK컴퍼니", ["SK", "에스케이"])


def test_to_record_maps_all_fields():
    rec = jobs.to_record(RAW, "hanwha", ["한화"])
    assert rec["title"] == "촉매 연구개발 경력사원 모집"
    assert rec["company_name"] == "한화솔루션(주)"
    assert rec["posted"] == "2026-08-10"
    assert rec["deadline"] == "2026-08-20"
    assert rec["job_type"] == "정규직"
    assert rec["experience"] == "경력 3~7년"
    assert rec["location"] == "서울 중구"
    assert rec["job_id"] == "50001"


def test_to_record_rejects_other_company():
    other = {**RAW, "company": {"detail": {"name": "무관회사"}}}
    assert jobs.to_record(other, "hanwha", ["한화"]) is None


def test_iso_date_accepts_timestamp():
    # 사람인은 ISO 8601 과 유닉스 타임스탬프를 모두 쓴다
    assert jobs._iso_date("2026-08-11T13:46:04+0900") == "2026-08-11"
    assert jobs._iso_date("") == ""


def test_is_open_uses_deadline():
    today = date(2026, 8, 11)
    assert jobs.is_open({"deadline": "2026-08-20"}, today)
    assert jobs.is_open({"deadline": "2026-08-11"}, today)      # 오늘 마감은 아직 열림
    assert not jobs.is_open({"deadline": "2026-08-10"}, today)
    assert jobs.is_open({"deadline": ""}, today)                # 상시채용


def test_cap_sorts_by_deadline_not_recency():
    """채용공고의 정렬 기준은 '최신' 이 아니라 '마감 임박' 이다."""
    records = [
        {"deadline": "2026-09-30", "posted": "2026-08-11", "job_id": "3"},
        {"deadline": "2026-08-13", "posted": "2026-08-01", "job_id": "1"},
        {"deadline": "", "posted": "2026-08-11", "job_id": "4"},        # 상시채용
        {"deadline": "2026-08-20", "posted": "2026-08-05", "job_id": "2"},
    ]
    kept = jobs.cap_per_company(records, limit=3)
    assert [r["job_id"] for r in kept] == ["1", "2", "3"]
    # 상시채용은 마감일 있는 공고보다 뒤로
    assert jobs.cap_per_company(records, limit=4)[-1]["job_id"] == "4"


def test_merge_duplicates_unions_companies():
    a = {**jobs.to_record(RAW, "hanwha", ["한화"])}
    b = {**jobs.to_record(RAW, "other", ["한화"])}
    merged = jobs.merge_duplicates([a, b])
    assert len(merged) == 1
    assert merged[0]["companies"] == ["hanwha", "other"]


def test_days_until_and_deadline_label():
    assert render.days_until("2026-08-14", "2026-08-11") == 3
    assert render.days_until("", "2026-08-11") is None
    assert render.format_deadline({"deadline": "2026-08-14", "days_left": 3}) == "D-3"
    assert render.format_deadline({"deadline": "2026-08-11", "days_left": 0}) == "오늘 마감"
    assert render.format_deadline({"deadline": "", "close_type": "상시채용"}) == "상시채용"


def test_group_jobs_marks_closing_soon():
    snapshot = render.build_snapshot(
        [], [],
        [{"companies": ["hanwha"], "title": "A", "deadline": "2026-08-14",
          "posted": "2026-08-01", "job_id": "1", "is_new": True},
         {"companies": ["hanwha"], "title": "B", "deadline": "2026-10-01",
          "posted": "2026-08-01", "job_id": "2", "is_new": False}],
    )
    snapshot["today"] = "2026-08-11"
    section = next(s for s in render.group_jobs(snapshot) if s["key"] == "hanwha")
    assert [e["title"] for e in section["entries"]] == ["A", "B"]   # 마감 임박 우선
    assert section["entries"][0]["closing_soon"] is True
    assert section["entries"][1]["closing_soon"] is False


def test_missing_key_raises_dedicated_error():
    import os
    saved = os.environ.pop("SARAMIN_API_KEY", None)
    try:
        raised = False
        try:
            jobs.api_key()
        except jobs.MissingKey:
            raised = True
        assert raised, "키가 없으면 MissingKey 여야 파이프라인이 채용만 건너뛴다"
    finally:
        if saved is not None:
            os.environ["SARAMIN_API_KEY"] = saved


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
