# 주간 연구 대시보드

화학공학 연구용 개인 대시보드. 매주 자동으로 논문·기업 뉴스를 수집해 GitHub Pages 단일 페이지로 배포한다.

## 수집 대상

**논문 4개 트랙** — 전기화학 촉매 / 유기 촉매 / PFAS 분해 / OER·HER
**기업 뉴스 8곳** — POSCO홀딩스, GS칼텍스, 삼성SDI, 삼성전자, 조선내화, 린데코리아, OCI홀딩스, 현대자동차
**채용공고 17곳** — HD현대, 한화, 현대자동차, 포스코, GS칼텍스, OCI홀딩스, 동서석유화학, 조선내화, LS, 삼성, 고려아연, SK, 현대IHL, 롯데, E1, S-OIL, GS바이오

## 구조

```
.github/workflows/weekly-update.yml   매주 실행 (논문·뉴스·채용)
.github/workflows/daily-jobs.yml      매일 실행 (채용공고만)
src/config.py                         저널·키워드·기업 목록
src/collectors/papers.py              논문 수집
src/collectors/news.py                기업 뉴스 수집
src/processors/dedupe.py              중복 제거·정규화
src/render.py                         data -> docs/index.html
data/papers, data/news                주차별 원본 아카이브
data/latest.json                      대시보드가 읽는 최신 스냅샷
docs/                                 GitHub Pages 배포 루트
templates/dashboard.html.j2           대시보드 템플릿
```

## 진행 상황

- [x] **STEP 0** 프로젝트 폴더 구조
- [x] **STEP 1** 논문 수집기 (Crossref)
- [x] **STEP 2** 기업 뉴스 수집기 (Google News RSS)
- [x] **STEP 3** 대시보드 렌더링 + GitHub Pages 자동 배포

## GitHub Pages 설정 (최초 1회)

1. 저장소를 GitHub에 push
2. **Settings → Pages → Source: "Deploy from a branch" → `main` / `/docs`**
3. **Settings → Secrets and variables → Actions** 에 시크릿 등록
   - `SARAMIN_API_KEY` — 채용공고 수집에 필요. 없으면 채용 섹션만 비워진다.
   - `CROSSREF_MAILTO` — (선택) Crossref polite pool. 없어도 동작한다.

이후 매주 월요일 09:00(KST)에 워크플로가 수집 → 렌더링 → 커밋하고,
`/docs` 변경이 Pages에 자동 반영된다. **Actions 탭 → weekly-update → Run workflow**
로 수동 실행도 된다.

## 로컬 실행

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt

python -m src.pipeline                        # 전체: 수집 -> 스냅샷 -> docs/index.html
python -m src.pipeline --render-only          # 수집 없이 다시 렌더링 (템플릿 수정 후)
python -m src.pipeline --from-archive         # 최신 주차 아카이브로 스냅샷 재구성
python -m src.pipeline --skip-news            # 논문만 다시 수집

python -m src.collectors.papers --days 7      # 논문만 -> data/papers/YYYY-Www.json
python -m src.collectors.news --days 7        # 뉴스만 -> data/news/YYYY-Www.json
python -m src.collectors.jobs                 # 채용만 -> data/jobs/YYYY-Www.json

python tests/test_papers.py                   # 오프라인 테스트
python tests/test_news.py
python tests/test_jobs.py
python tests/test_render.py
```

채용공고를 쓰려면 키가 필요하다:

```bash
$env:SARAMIN_API_KEY = "발급받은키"     # PowerShell
export SARAMIN_API_KEY=발급받은키       # bash
```

생성된 `docs/index.html` 은 브라우저로 바로 열어 확인할 수 있다.

`CROSSREF_MAILTO` 환경변수에 이메일을 넣으면 Crossref polite pool로 처리돼 응답이 안정적이다.

## 논문 수집 동작

키워드로 검색하지 않고 **대상 저널의 신규 등록 논문을 전량 받아 로컬에서 분류**한다.
Crossref 키워드 검색은 관련도 기반이라 검색어가 없는 논문도 섞여 들어오는데,
저널이 10종 내외라 전량 조회가 더 정확하다.

수집 창의 기준은 `created-date`(Crossref 최초 등록일)다. 다른 두 후보는 이렇게 실패했다:

| 기준 | 문제 | 실측 |
|---|---|---|
| `index-date` | 출판사가 과거 논문 메타데이터를 일괄 갱신하면 색인일이 최신으로 바뀜 | JACS 1주에 14,754건 |
| `pub-date` | RSC 등은 출판일을 연도 단위로만 등록해 하한 필터에 전멸 | EES 1주 2,066건 → 0건 |
| `created-date` | 항상 일 단위, 최초 등록 시점에만 기록 | Nature 77건/주 (정상) |

주제 분류는 `config.TOPICS` 의 네 필드로 조정한다 — `terms`(부분 문자열),
`acronyms`(대소문자 구분), `context`(추가로 필요한 맥락), `exclude`(제외).
예를 들어 PFAS 트랙은 분해/처리 맥락을 요구해 독성·노출 역학 논문을 걸러내고,
`fluoroalkylation` 같은 불소화 **합성** 논문은 제외한다 (분해의 반대 방향).

### 대상 저널 30종

종합지 5 · 촉매 10 · 에너지 5 · 환경 6 · 유기합성 4. ISSN 은 전부
`works?filter=issn:...` 로 실제 반환 저널명을 확인해 넣은 값이다.
`Nature`·`Science`·`Chem` 처럼 이름이 짧거나 `&` 가 든 저널은 journals API
자동 조회가 실패하므로 ISSN 을 직접 넣어야 한다.

### 알아둘 한계: Elsevier 저널은 초록이 없다

Crossref 에 초록을 등록하지 않는 출판사가 있다. 실측으로 Water Research 0/54,
Journal of Hazardous Materials 0/76 이 초록 없이 내려온다. 이 저널들은
**제목만으로** 분류되므로 다른 저널보다 재현율이 낮다. 그래서 키워드는
어간 위주로 넓게 잡되(`perfluoro`), `context`/`exclude` 로 정밀도를 잡는다.

### 주제별 상한

`MAX_PAPERS_PER_TOPIC`(기본 30) 을 넘으면 최신순으로 자른다. 저널 30종 기준
전기화학 촉매는 주당 60편대가 나와 상한에 걸린다. 잘린 편수는 대시보드에
`총 66편 중 30편` 으로 표시되므로 조용히 사라지지 않는다.

## 뉴스 수집 동작

Google News RSS 를 기업별로 조회한다. API 키가 필요 없고 한국어 매체 커버리지가 넓다.
`config.COMPANIES` 의 `aliases` 를 OR 로 묶어 질의한다.

세 가지 보정이 들어간다:

- **KST 변환** — RSS 는 GMT 로 오기 때문에 변환하지 않으면 밤 기사가 전날 날짜로 찍힌다.
- **제목 매칭 우선** — 회사명이 제목에 있는 기사를 먼저 채우고, 본문에만 언급된 기사는
  최대 `MAX_BODY_ONLY_NEWS` 건까지만 채운다. Google News 는 회사가 스치듯 언급된
  기사도 물어온다 (실측: '조선내화' 검색에 지자체 폭염 대응 기사).
- **주가 기사 제외** — `NEWS_EXCLUDE_TITLE_TERMS`. 자동생성 시세 기사가 상위를 덮는다
  (실측: OCI홀딩스 상위 5건 중 4건).

기사량이 적은 회사는 7일 창에서 제목 매칭이 0건이면 `NEWS_FALLBACK_DAYS`
(30 → 90 → 180일) 순으로 창을 넓힌다. 린데코리아는 180일에 10건 수준이라
고정 7일 창으로는 매주 빈 칸이 된다. 아카이브 기준 중복 제거가 있어
창을 넓혀도 같은 기사가 다시 노출되지는 않는다.

## 채용공고 수집 동작

[사람인 오픈 API](https://oapi.saramin.co.kr) 를 쓴다. 실측해보니 키 없이 실제 공고를
받을 수 있는 경로가 없었다 — 회사 채용 사이트는 봇 차단(포스코·HD현대)이거나
JS 렌더링이고, Google News 로는 공고가 아니라 채용 *기사* 가 온다.

`SARAMIN_API_KEY` 환경변수(Actions 에서는 같은 이름의 시크릿)가 필요하다.
**키가 없으면 채용 수집만 건너뛰고 논문·뉴스는 정상 동작한다.**
호출은 기업당 1회, 주 17회로 일일 한도(500회)에 여유가 크다.

### 채용 사이트 바로가기

API 로 받는 '공고' 와 별개로, 각 사 **공식 채용 페이지 링크**를 채용 섹션 상단에
함께 둔다 (`config.CAREER_SITES`, 18곳). 대기업 공채는 자사 사이트에만 올리는
경우가 많아 API 수집만으로는 놓치기 때문이다. 키가 없어도 항상 표시된다.

URL 은 전부 HTTP 200 을 확인하고 넣었다. 전용 채용 사이트가 없는 4곳
(동서석유화학·조선내화·현대IHL·GS바이오)은 사람인 검색으로 연결하고,
링크에 `사람인` 이라고 출처를 글자로 밝힌다. 링크가 깨지면 `CAREER_SITES` 만 고치면 된다.

### 갱신 주기

채용공고만 **매일** 갱신한다 (`daily-jobs.yml`, 08:00 KST). 논문·뉴스는 주 단위로
충분하지만 채용공고는 마감일이 걸려 있어 하루만 밀려도 지원 기회를 놓친다.
일일 워크플로는 `--skip-papers --skip-news` 로 돌아 논문·뉴스는 직전 스냅샷 값을
그대로 유지하므로 덮어쓰지 않는다. 두 워크플로는 같은 `data/`·`docs/` 를 건드려서
`concurrency: dashboard-update` 그룹을 공유해 동시 실행을 막는다.

### 어떤 직무가 올라왔는지

공고마다 직무를 분류해 배지로 달고, 채용 섹션 위에 **올라온 직무 요약**을 둔다
(`config.JOB_ROLES`, 9개 버킷 — 플랜트·시운전 / 연구개발 / 생산·공정 / 품질·분석 /
설비·정비 / 환경·안전 / 영업·구매 / IT·데이터 / 경영지원).

분류는 **공고 제목을 먼저** 보고, 안 걸리면 사람인 직무명(`job-code`)으로 본다.
사람인 분류는 표준이라 화학공학 관점과 어긋날 때가 있다 — 시운전이 '생산/제조' 로
뭉뚱그려지는 식이다. 버킷과 키워드는 `JOB_ROLES` 에서 조정한다.

### 논문·뉴스와 다른 점

채용공고는 '이번 주 신규' 가 아니라 **'지금 지원 가능한가'** 가 핵심이다. 그래서

- 지난주에 이미 본 공고도 **마감 전이면 계속 표시**한다 (중복 제거로 지우지 않는다).
- 정렬은 최신순이 아니라 **마감 임박순**이다. 상시채용은 뒤로 보낸다.
- 직전 주차에 없던 공고에는 `신규`, 마감이 `JOB_DEADLINE_SOON_DAYS`(기본 7일)
  안이면 `D-3` 같은 잔여일과 함께 강조 배지를 단다.

### 회사명 대조

사람인의 `keywords` 는 회사명뿐 아니라 공고 제목·업종·본문까지 훑기 때문에 다른
회사 공고가 섞여 온다. 등록 회사명(`company.detail.name`)이 별칭과 맞는 것만 남긴다.
그룹명(`한화`, `삼성`)을 넣으면 계열사가 모두 걸린다.

`LS` `SK` `E1` 처럼 짧은 라틴 별칭은 앞뒤에 라틴 문자·숫자가 없을 때만 인정한다.
부분 문자열로 찾으면 `TOOLS코리아` 가 `LS` 로 걸리고, `\b` 는 한글이 단어 문자로
취급돼 `LS전선` 에서 경계가 생기지 않아 쓸 수 없다.

## 대시보드

`data/latest.json` → Jinja2 템플릿 → `docs/index.html`.
스타일과 스크립트는 생성물이 아니라 `docs/assets/` 의 실제 파일이라 직접 고치면 된다.

### 디자인

민트 배경 + 딥그린 프라이머리, 26~30px 라운드 카드, 부드러운 그림자,
스티키 블러 헤더, 대문자 kicker, 딥그린 히어로 패널과 푸터.

주제 색(초록·파랑·테라코타·바이올렛)은 이 톤에 맞춰 고른 뒤 색각 이상
검증기로 통과 조합만 남긴 값이다 — 인접 배치 최악 CVD ΔE **17.1** 로
라이트/다크 모두 통과한다. **순서 자체가 안전장치라 임의로 바꾸면 안 되고,
색을 바꿀 때는 검증기를 다시 돌려야 한다.** 그래도 대시보드는

- 주제마다 카드를 나눠 **한 구역에 한 색만** 놓고,
- 히어로 막대 옆에 **숫자를 함께** 적으며,
- 주제명·기업명을 항상 **글자로 함께** 표기한다 (색만으로 뜻을 전달하지 않음).

라이트/다크 모두 명시적으로 정의했고, 토글 선택은 `localStorage` 에 남는다.
선택한 적이 없으면 OS 설정을 따른다. 두 모드의 텍스트·칩 대비는 전부
계산으로 확인했다 (본문 4.5:1, 주제색 표식 3:1 이상).
