"""논문 수집기 오프라인 테스트 (네트워크 없이 분류·정제·중복 제거만 검증).

    pytest tests/            또는            python tests/test_papers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collectors import papers  # noqa: E402
from src.processors import dedupe  # noqa: E402


def test_match_topics_stem():
    assert "electrocatalysis" in papers.match_topics(
        "A stable electrocatalytic system for CO2 reduction"
    )


def test_match_topics_acronym_is_case_sensitive():
    # 대문자 HER = 수소 발생 반응
    assert "oer_her" in papers.match_topics("Ni-based catalysts for the HER in alkaline media")
    # 소문자 her = 영어 대명사, 매칭되면 안 됨
    assert "oer_her" not in papers.match_topics("A study of her research group methodology")


def test_match_topics_multiple():
    hits = papers.match_topics(
        "Single-atom electrocatalyst for the oxygen evolution reaction"
    )
    assert set(hits) == {"electrocatalysis", "oer_her"}


def test_match_topics_none():
    assert papers.match_topics("Crystal structure of a membrane protein") == []


def test_pfas_requires_degradation_context():
    # 분해/처리 맥락 있음 -> 채택
    assert papers.match_topics(
        "Electrochemical defluorination of PFOA in water treatment"
    ) == ["pfas"]
    # 독성·노출 역학 논문 -> 제외
    assert papers.match_topics(
        "Predictors of serum per- and polyfluoroalkyl substance concentrations in children"
    ) == []


def test_pfas_matches_specific_compound_names():
    # 실측 누락 사례: 초록 없는 Elsevier 저널에서 제목만으로 판정되는데
    # 'perfluoroalkyl' 로 좁게 잡으면 개별 물질명을 놓친다
    assert papers.match_topics(
        "Electrochemical reduction degradation and defluorination of "
        "perfluorooctane sulfonate"
    ) == ["pfas"]
    assert papers.match_topics(
        "Perfluorohexane sulfonate (PFHxS) removal by regenerable adsorbents"
    ) == ["pfas"]
    # 넓혀도 노출·독성 논문은 여전히 걸러져야 한다
    assert papers.match_topics(
        "Prenatal exposure to perfluorooctanoic acid and child bone mineral density"
    ) == []


def test_pfas_excludes_fluorination_synthesis_and_electrolytes():
    # C-F 결합을 만드는 합성 연구는 분해의 반대다 (실측 오탐 사례)
    assert "pfas" not in papers.match_topics(
        "Diboron-enabled nickel-catalyzed reductive hydroperfluoroalkylation "
        "toward beta-perfluoroalkyl amides"
    )
    assert "pfas" not in papers.match_topics(
        "Phototriggered self-catalyzed multicomponent fluoroalkylation of N-heteroarenes"
    )
    # 불소계 배터리 전해질도 주제가 아니다
    assert "pfas" not in papers.match_topics(
        "Perfluorinated asymmetric magnesium salts enable stable and "
        "dendrite-free magnesium battery electrolyte"
    )


def test_organocatalysis_excludes_biocatalysis_and_metal():
    assert papers.match_topics(
        "Biocatalytic dynamic kinetic resolution with a chiral catalyst"
    ) == []
    assert papers.match_topics(
        "Alternating copolymerization by a dual-site Grubbs catalyst with a chiral catalyst"
    ) == []


def test_oer_her_excludes_battery_papers():
    assert papers.match_topics(
        "Isotopic engineering of water reactivity suppressing HER in aqueous iron-metal batteries"
    ) == []


def test_is_editorial():
    assert papers.is_editorial('Correction to "PFAS Toxicity: What Really Matters"')
    assert papers.is_editorial("Correspondence on defluorination of fluorotelomers")
    assert papers.is_editorial("Back Cover")
    # 본문 중간의 'comment' 는 정상 논문
    assert not papers.is_editorial("A comment-free analysis of electrocatalytic pathways")


def test_editorial_notice_is_dropped():
    item = {
        "title": ['Correction to "Defluorination of PFOA over a catalyst"'],
        "DOI": "10.1/x",
    }
    assert papers.to_record(item, "ES&T") is None


def test_clean_abstract_strips_jats():
    raw = "<jats:p>Abstract: PFAS are <jats:italic>persistent</jats:italic> &amp; toxic.</jats:p>"
    assert papers.clean_abstract(raw) == "PFAS are persistent & toxic."


def test_clean_text_fixes_entities_and_newlines():
    # Crossref가 실제로 이런 형태로 내려준다
    assert papers.clean_text("Journal of the American\nChemical Society") == \
        "Journal of the American Chemical Society"
    assert papers.clean_text("Environmental Science &amp;\nTechnology") == \
        "Environmental Science & Technology"


def test_to_record_skips_unmatched():
    item = {"title": ["A protein folding study"], "DOI": "10.1/x"}
    assert papers.to_record(item, "Nature") is None


def test_to_record_builds_schema():
    item = {
        "title": ["Defluorination of PFOA over a novel catalyst"],
        "DOI": "10.1021/ABC123",
        "author": [{"given": "Jane", "family": "Doe"}],
        "container-title": ["Environmental Science & Technology"],
        "published-online": {"date-parts": [[2026, 8, 3]]},
        "URL": "https://doi.org/10.1021/abc123",
        "abstract": "<jats:p>We report defluorination.</jats:p>",
    }
    rec = papers.to_record(item, "ES&T")
    assert rec["topics"] == ["pfas"]
    assert rec["doi"] == "10.1021/abc123"
    assert rec["published"] == "2026-08-03"
    assert rec["published_precision"] == "day"
    assert rec["authors"] == ["Jane Doe"]
    assert rec["journal"] == "Environmental Science & Technology"


def test_date_falls_back_to_issued():
    item = {"issued": {"date-parts": [[2026, 7]]}}
    assert papers._published(item) == ("2026-07-01", "month")


def test_year_only_date_is_marked_low_precision():
    # RSC 등은 연도만 등록한다. 1월 1일로 채우되 정밀도로 구분할 수 있어야 한다.
    assert papers._published({"issued": {"date-parts": [[2026]]}}) == ("2026-01-01", "year")


def test_published_prefers_online_over_print():
    item = {
        "published-online": {"date-parts": [[2026, 8, 3]]},
        "published-print": {"date-parts": [[2026, 9, 1]]},
    }
    assert papers._published(item)[0] == "2026-08-03"


def test_normalize_doi():
    assert dedupe.normalize_doi("https://doi.org/10.1/ABC") == "10.1/abc"
    assert dedupe.normalize_doi("10.1/abc") == "10.1/abc"


def test_dedupe_removes_seen_and_batch_duplicates():
    records = [
        {"doi": "10.1/a", "title": "A", "topics": ["pfas"]},
        {"doi": "10.1/A", "title": "A again", "topics": ["pfas"]},   # 대소문자만 다름
        {"doi": "10.1/b", "title": "B", "topics": ["pfas"]},
    ]
    fresh = dedupe.dedupe_papers(records, seen_dois={"10.1/b"})
    assert [r["doi"] for r in fresh] == ["10.1/a"]


def test_archive_name_uses_iso_week():
    from datetime import date
    assert dedupe.archive_name(date(2026, 8, 11)) == "2026-W33.json"


def test_current_week_archive_is_excluded_from_seen():
    """같은 주 재실행이 그 주 데이터를 지우면 안 된다 (실제로 겪은 사고).

    아카이브 폴더의 *.json 을 전부 '이미 노출됨' 으로 읽으면, 재실행 시
    방금 저장한 이번 주 파일이 자기 자신을 걸러내고 빈 결과로 덮어쓴다.
    """
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        (directory / "2026-W32.json").write_text(
            json.dumps({"papers": [{"doi": "10.1/old"}]}), encoding="utf-8")
        (directory / "2026-W33.json").write_text(
            json.dumps({"papers": [{"doi": "10.1/thisweek"}]}), encoding="utf-8")

        # 제외하지 않으면 이번 주 DOI 까지 '이미 봤음' 이 된다
        assert dedupe.load_seen_dois(directory) == {"10.1/old", "10.1/thisweek"}
        # 이번 주 파일을 빼면 지난 주 것만 남는다
        assert dedupe.load_seen_dois(directory, exclude="2026-W33.json") == {"10.1/old"}

        # 뉴스도 같은 규칙
        (directory / "2026-W33.json").write_text(
            json.dumps({"news": [{"url": "https://a/1", "title": "이번 주"}]}),
            encoding="utf-8")
        assert dedupe.load_seen_news(directory, exclude="2026-W33.json") == set()


def test_cap_per_topic_keeps_newest():
    records = [
        {"doi": f"10.1/{i}", "title": str(i), "topics": ["pfas"], "published": f"2026-08-{i:02d}"}
        for i in range(1, 6)
    ]
    kept = papers.cap_per_topic(records, limit=2)
    assert [r["published"] for r in kept] == ["2026-08-05", "2026-08-04"]


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
