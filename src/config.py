"""수집 대상 설정: 주제 키워드, 저널 목록, 기업 목록.

STEP 0에서는 설정 뼈대만 정의한다. 실제 수집 로직은 STEP 1(논문), STEP 2(뉴스)에서 작성.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. 논문 주제 (4개 트랙)
#    key      : 내부 식별자
#    label    : 대시보드 표시명
#    terms    : 대소문자 무시 부분 문자열. 어간만 적으면 활용형까지 잡힌다
#               (예: "electrocataly" -> electrocatalysis / -catalyst / -catalytic)
#    acronyms : 대소문자 구분 + 단어 경계 매칭. 흔한 영단어와의 오탐을 막는다
#               (예: "HER" 는 대문자일 때만 수소 발생 반응으로 인정)
#    context  : (선택) terms/acronyms 가 걸린 뒤 **추가로** 하나 이상 나와야
#               인정한다. 주제어는 맞는데 관심사가 다른 논문을 걸러낸다
#               (예: PFAS 독성·노출 역학 논문 -> 분해/처리 맥락 없으면 제외)
#    exclude  : (선택) 하나라도 나오면 제외한다
# ---------------------------------------------------------------------------
#    color/color_dark : 대시보드 주제 색. 민트-그린 페이지 톤에 맞춰 고른 뒤
#               색각 이상 검증기로 통과 조합만 남긴 값이다 (초록·파랑·테라코타·바이올렛).
#               인접 배치 기준 최악 CVD ΔE 17.1 로 두 모드 모두 통과한다.
#               순서 자체가 안전장치이므로 임의로 바꾸면 안 되고, 색을 바꿀 때는
#               반드시 검증기를 다시 돌릴 것.
#               그래도 대시보드는 주제별로 섹션을 나눠 한 화면 구역에 한 색만 놓고,
#               색과 무관하게 주제명을 항상 글자로 함께 표기한다.
TOPICS: list[dict] = [
    {
        "key": "electrocatalysis",
        "label": "전기화학 촉매",
        "color": "#219761",
        "color_dark": "#2a9d67",
        "terms": [
            "electrocataly",
            "electrochemical catalys",
            "electrode catalys",
        ],
        "acronyms": [],
    },
    {
        "key": "organocatalysis",
        "label": "유기 촉매",
        "color": "#3a84ca",
        "color_dark": "#418ad1",
        "terms": [
            "organocataly",
            "metal-free catalys",
            "chiral catalyst",
            "enamine catalys",
            "iminium catalys",
            "hydrogen-bond donor catalys",
            "thiourea catalys",
            "phosphoric acid catalys",
            "chiral amine catalys",
        ],
        "acronyms": ["NHC"],
        # NHC·chiral 만으로는 배위화학·재료 논문이 딸려 온다. 촉매 맥락을 요구.
        "context": ["catalys", "catalyt"],
        # 금속 촉매·효소 촉매는 유기 촉매가 아니다
        "exclude": ["biocatalyt", "biocataly", "enzymatic catalys", "grubbs"],
    },
    {
        "key": "pfas",
        "label": "PFAS 분해",
        "color": "#be6438",
        "color_dark": "#c56a3e",
        # 'perfluoroalkyl' 처럼 좁게 잡으면 개별 물질명을 놓친다. 어간 'perfluoro'
        # 로 넓혀야 perfluorooctane / perfluorohexane / perfluorooctanoic 이 잡힌다.
        # (실측: Water Research 의 'Electrochemical reduction degradation and
        #  defluorination of perfluorooctane sulfonate' 가 누락됐다)
        # 넓혀도 아래 context 조건이 독성·노출 논문을 걸러 준다.
        "terms": [
            "perfluoro",
            "polyfluoro",
            "fluorotelomer",
            "fluorinated pollutant",
            "fluorinated contaminant",
            "forever chemical",
        ],
        "acronyms": ["PFAS", "PFOA", "PFOS", "PFCA", "PFSA", "PFHxS", "PFBS", "PFNA", "PFBA"],
        # 관심사는 '분해'다. 독성·노출 역학 논문을 걸러내기 위해 처리 맥락을 요구한다.
        # 'reduction' / 'oxidation' / 'catalys' 같은 일반어는 뺐다. 이런 단어는
        # 어느 합성 논문에나 있어서, 어간을 'perfluoro' 로 넓히자마자
        # 불소화 합성 논문이 통째로 딸려 왔다.
        "context": [
            "defluorinat", "degrad", "destruct", "mineraliz", "decompos",
            "remediat", "treatment", "removal", "remov", "adsorb", "adsorpt",
            "sorption", "regenerat", "photolys", "advanced oxidation",
            "contaminat", "wastewater", "groundwater", "drinking water",
        ],
        # C-F 결합을 '만드는' 연구는 분해의 반대다. 불소계 전해질도 주제가 아니다.
        "exclude": [
            "fluoroalkylation", "trifluoromethylation", "fluorination reagent",
            "electrolyte", "battery", "batteries", "dendrite",
        ],
    },
    {
        "key": "oer_her",
        "label": "OER / HER",
        "color": "#866ec5",
        "color_dark": "#8c74cc",
        "terms": [
            "oxygen evolution",
            "hydrogen evolution",
            "water splitting",
            "water electrolysis",
        ],
        "acronyms": ["OER", "HER"],
        # 배터리 논문이 부반응으로 HER 을 언급하는 경우가 잦다
        "exclude": ["battery", "batteries"],
    },
]

# 논문이 아닌 편집 공지. Crossref 에서는 이것도 type=journal-article 로 온다.
# 제목 맨 앞에서만 판정한다 (본문에 'comment' 가 들어간 정상 논문 보호).
EXCLUDE_TITLE_PREFIXES: list[str] = [
    "correction", "corrigendum", "erratum", "retraction", "retracted",
    "addendum", "expression of concern", "comment on", "comments on",
    "reply to", "response to comment", "correspondence on", "rebuttal",
    "editorial", "front cover", "back cover", "inside cover", "cover feature",
    "issue information", "masthead", "table of contents", "contents",
    "graphical abstract", "author index", "erratum to",
]

# ---------------------------------------------------------------------------
# 2. 대상 저널 (30종)
#
#    issn 은 전부 Crossref works 엔드포인트로 실제 반환 저널명을 확인해 넣은
#    값이다 (인쇄판/온라인판을 함께 넣으면 Crossref가 OR로 처리한다).
#    저널을 추가할 때 issn 을 비워두면 Crossref journals API 로 자동 조회해
#    data/journals.json 에 캐시한다. 단 이름이 짧거나(Nature, Science, Chem)
#    '&' 가 들어가면 자동 조회가 실패하므로 그때는 직접 채워 넣을 것.
#    확인 방법: works?filter=issn:XXXX-XXXX 로 조회해 container-title 을 본다.
# ---------------------------------------------------------------------------
JOURNALS: list[dict] = [
    # ── 종합지 ────────────────────────────────────────────────────────
    # 이 4개 주제에 대한 산출은 주당 0~1편 수준이지만, 리드미 급 논문을
    # 놓치지 않기 위해 유지한다. 조회 비용은 저널당 1~2회 요청뿐이다.
    {"name": "Nature", "issn": ["0028-0836", "1476-4687"]},
    {"name": "Science", "issn": ["0036-8075", "1095-9203"]},
    {"name": "Nature Chemistry", "issn": ["1755-4330", "1755-4349"]},
    {"name": "Nature Materials", "issn": ["1476-1122", "1476-4660"]},
    {"name": "Nature Nanotechnology", "issn": ["1748-3387", "1748-3395"]},

    # ── 촉매 ──────────────────────────────────────────────────────────
    {"name": "Nature Catalysis", "issn": ["2520-1158"]},
    {"name": "ACS Catalysis", "issn": ["2155-5435"]},
    {"name": "Journal of the American Chemical Society", "issn": ["0002-7863", "1520-5126"]},
    {"name": "JACS Au", "issn": ["2691-3704"]},
    {"name": "Angewandte Chemie International Edition", "issn": ["1433-7851", "1521-3773"]},
    {"name": "Chem", "issn": ["2451-9294"]},
    {"name": "Chem Catalysis", "issn": ["2667-1093"]},
    {"name": "Chemical Science", "issn": ["2041-6520", "2041-6539"]},
    {"name": "Journal of Catalysis", "issn": ["0021-9517", "1090-2694"]},
    # 2024년 'Applied Catalysis B: Environment and Energy' 로 개명됨
    {"name": "Applied Catalysis B: Environment and Energy", "issn": ["0926-3373"]},

    # ── 에너지·전기화학 ───────────────────────────────────────────────
    {"name": "Nature Energy", "issn": ["2058-7546"]},
    {"name": "Energy & Environmental Science", "issn": ["1754-5692", "1754-5706"]},
    {"name": "Joule", "issn": ["2542-4351"]},
    {"name": "ACS Energy Letters", "issn": ["2380-8195"]},
    {"name": "Advanced Energy Materials", "issn": ["1614-6832", "1614-6840"]},

    # ── 환경·PFAS ─────────────────────────────────────────────────────
    {"name": "Environmental Science & Technology", "issn": ["0013-936X", "1520-5851"]},
    {"name": "Environmental Science & Technology Letters", "issn": ["2328-8930"]},
    {"name": "Environmental Science: Water Research & Technology", "issn": ["2053-1400", "2053-1419"]},
    {"name": "Water Research", "issn": ["0043-1354"]},
    {"name": "Journal of Hazardous Materials", "issn": ["0304-3894"]},
    {"name": "Chemical Engineering Journal", "issn": ["1385-8947"]},

    # ── 유기합성 ──────────────────────────────────────────────────────
    {"name": "Organic Letters", "issn": ["1523-7060", "1523-7052"]},
    {"name": "The Journal of Organic Chemistry", "issn": ["0022-3263", "1520-6904"]},
    {"name": "Green Chemistry", "issn": ["1463-9262", "1463-9270"]},
    {"name": "Organic Process Research & Development", "issn": ["1083-6160", "1520-586X"]},
]

# ---------------------------------------------------------------------------
# 3. 기업 뉴스 대상 (8곳)
# ---------------------------------------------------------------------------
#    aliases[0] 이 검색 기준이고, 나머지는 OR 로 함께 질의한다.
#    제목에 별칭이 없으면 '본문 언급' 기사로 보고 후순위로 밀린다.
COMPANIES: list[dict] = [
    {"key": "posco", "label": "POSCO홀딩스",
     "aliases": ["포스코홀딩스", "POSCO홀딩스", "포스코"]},
    {"key": "gscaltex", "label": "GS칼텍스",
     "aliases": ["GS칼텍스", "지에스칼텍스", "GS Caltex"]},
    {"key": "samsung_sdi", "label": "삼성SDI",
     "aliases": ["삼성SDI", "삼성 SDI", "Samsung SDI"]},
    {"key": "samsung_elec", "label": "삼성전자",
     "aliases": ["삼성전자", "Samsung Electronics"]},
    {"key": "chosun_refractories", "label": "조선내화",
     "aliases": ["조선내화"]},
    {"key": "linde_korea", "label": "린데코리아",
     "aliases": ["린데코리아", "린데 코리아", "Linde Korea", "린데그룹", "린데가스"]},
    {"key": "oci", "label": "OCI홀딩스",
     "aliases": ["OCI홀딩스", "OCI 홀딩스"]},
    {"key": "hyundai_motor", "label": "현대자동차",
     "aliases": ["현대자동차", "현대차", "Hyundai Motor"]},
]

# ---------------------------------------------------------------------------
# 4. 수집 범위 / 경로
# ---------------------------------------------------------------------------
LOOKBACK_DAYS = 7           # 매주 실행 기준 조회 기간
# 주제당 상한. 저널 30종 기준 전기화학 촉매는 주당 60편대가 나와서 상한에 걸린다.
# 잘린 건수는 대시보드에 '총 N편 중 M편' 으로 표시하므로 조용히 사라지지 않는다.
MAX_PAPERS_PER_TOPIC = 30
MAX_NEWS_PER_COMPANY = 5    # 기업당 상한

# Crossref 색인 시점(from-index-date) 기준으로 조회하므로, 오래 전에 출판됐다가
# 뒤늦게 색인된 논문이 섞여 들어온다. 출판일이 이보다 오래되면 버린다.
MAX_AGE_DAYS = 180

DATA_DIR = "data"
PAPERS_DIR = "data/papers"
NEWS_DIR = "data/news"
JOURNAL_CACHE = "data/journals.json"
LATEST_SNAPSHOT = "data/latest.json"
OUTPUT_HTML = "docs/index.html"
TEMPLATE = "templates/dashboard.html.j2"

# ---------------------------------------------------------------------------
# 5. Crossref API
#    mailto 를 넣으면 polite pool 로 처리돼 응답이 안정적이다.
#    이메일이 저장소에 남지 않도록 환경변수(CROSSREF_MAILTO)로만 받는다.
# ---------------------------------------------------------------------------
CROSSREF_API = "https://api.crossref.org"
CROSSREF_ROWS = 200         # 페이지당 행 수 (최대 1000)
REQUEST_TIMEOUT = 30        # 초
REQUEST_DELAY = 0.3         # 연속 요청 간 대기(초). 없으면 429가 난다
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# 6. 뉴스 (Google News RSS)
#    API 키가 필요 없고 한국어 매체 커버리지가 넓어 이걸 쓴다.
#    링크는 news.google.com 리다이렉트 주소이며 브라우저에서 원문으로 넘어간다.
# ---------------------------------------------------------------------------
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
NEWS_LOCALE = {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}
# 한국 기업 뉴스라 KST 기준으로 날짜를 매긴다. RSS는 GMT로 오기 때문에
# 변환하지 않으면 밤 기사가 전날로 표시된다. KST는 서머타임이 없어 고정 오프셋.
KST_OFFSET_HOURS = 9

# 기사량이 적은 회사는 7일 창으로는 매주 빈 칸이 된다 (실측: 린데코리아 180일에 10건).
# 제목에 회사명이 걸린 기사가 하나도 없으면 이 순서로 창을 넓힌다.
# 아카이브 기준 중복 제거가 있어 넓혀도 같은 기사가 반복 노출되지는 않는다.
NEWS_FALLBACK_DAYS = [30, 90, 180]

# 회사명이 제목에 없는 '본문 언급' 기사 상한.
# Google News 는 회사가 스치듯 언급된 기사도 물어온다
# (실측: '조선내화' 검색에 지자체 폭염 대응 기사가 섞임).
MAX_BODY_ONLY_NEWS = 2

# 자동생성 주가/시황 기사 제외. 관심사는 사업 동향이지 시세가 아니다
# (실측: OCI홀딩스 상위 5건 중 4건이 '주가, 8월 11일 장중 274,500원 3.51% 하락' 류).
# 제목 어디에나 있으면 제외하므로, 놓치는 기사가 있으면 항목을 빼면 된다.
NEWS_EXCLUDE_TITLE_TERMS: list[str] = [
    "주가", "장중", "상한가", "하한가", "투자분석", "시황", "종목",
    "코스피", "코스닥", "수급", "매수", "매도", "차익실현", "체결강도",
    "상승 마감", "하락 마감", "52주 신고가", "공매도",
]
