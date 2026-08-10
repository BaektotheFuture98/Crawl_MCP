# JobKorea 채용·회사 검색 설계

작성일: 2026-08-06 (Asia/Seoul)

## 1. 목적

기존 범용 크롤링 MCP에 잡코리아 전용 채용 검색 기능을 추가한다. 외부 검색엔진의
색인이나 캐시를 사용하지 않고, 잡코리아 내부 채용목록 화면에 현재 표시되는 공개
공고를 검색의 기준으로 삼는다.

채용 결과에는 목록 정보뿐 아니라 다음 정보를 포함한다.

- 전체 JD 원문과 구조화된 주요 업무, 필수 자격요건, 우대사항, 복리후생
- 접수 시작일, 마감일, 마감 방식과 현재 지원 가능 여부
- JD에 명시된 기술 스택, 요구 수준과 근거 문구
- 회사 요약 정보와 현재 채용공고 연결
- 이용권한이 있는 경우의 회사 상세정보 검색

검색어는 코드에 고정하지 않는다. MCP 호출자가 임의의 채용 검색어와 회사명을
런타임 입력으로 전달한다. `데이터 엔지니어`는 테스트와 문서의 예시일 뿐이다.

## 2. 기준과 제약

### 2.1 검색 기준

- 채용공고의 source of truth는 잡코리아 `/recruit/joblist` 내부 검색 결과다.
- 외부 검색엔진 결과, 검색엔진 캐시와 직접 알고 있는 상세 URL은 검색 입력으로
  사용하지 않는다.
- 상세 URL이 열리더라도 현재 내부 검색 목록에 없으면 검색 결과에 포함하지 않는다.
- 검색 목록과 상세 페이지의 상태를 함께 확인해야만 지원 가능 여부를 판정한다.
- 검색 결과가 없으면 오류가 아닌 빈 결과를 반환한다.

### 2.2 접근 정책

- 공개 비로그인 채용 목록과 상세 공고만 지원한다.
- 로그인, 관심공고, 입사지원, 개인화 추천은 범위에서 제외한다.
- CAPTCHA, 접근 차단과 rate limit을 우회하지 않는다.
- robots.txt가 허용하지 않는 문서 또는 데이터 경로가 필요하면 작업을 중단하고
  `JOB_SEARCH_NOT_PERMITTED`를 반환한다.
- 동시 상세 요청 기본값은 1, 요청 간격 기본값은 2초다.
- 채용 검색 최대 반환값은 기본 20건, 운영자 상한은 100건이다.

### 2.3 회사정보 권한

잡코리아 기업정보에는 잡코리아 및 NICE평가정보 기반 데이터가 포함될 수 있고,
공식 기업 페이지에는 무단 수집·배포 금지 안내가 표시된다. 따라서 상세 회사정보는
잡코리아 API 승인 또는 별도 이용권한이 활성화된 경우에만 원격 수집한다.

권한이 없는 기본 모드에서는 채용 검색 과정에서 합법적으로 확인된 최소 회사 요약만
저장한다.

- 회사 ID와 이름
- 산업 및 기업구분(공고에 표시된 경우)
- 잡코리아 회사 페이지 URL
- 현재 검색에서 발견된 채용공고

매출, 사원수, 자본금, 대표자, 기업소개, 복리후생 같은 상세정보는
`AuthorizedCompanyProvider`를 통해서만 제공한다.

참고:

- 잡코리아 채용목록: <https://www.jobkorea.co.kr/recruit/joblist>
- 잡코리아 robots.txt: <https://www.jobkorea.co.kr/robots.txt>
- 잡코리아 API 안내: <https://www.jobkorea.co.kr/service/api>

## 3. 아키텍처

기존 헥사고날 아키텍처를 유지하면서 채용·회사 검색을 별도 Application Service로
분리한다.

```text
MCP search_jobs / search_companies / get_company
                         ↓
          JobSearchService / CompanySearchService
                         ↓
       JobSearchProvider / CompanySearchProvider Ports
                         ↓
    JobKoreaSearchAdapter / AuthorizedCompanyProvider
                         ↓
       공유 BrowserManager / Repository / 정책 계층
```

### 3.1 컴포넌트 책임

`JobSearchService`:

- 검색 요청 검증 이후 Provider를 선택한다.
- robots, URL 보안, timeout과 결과 상한을 적용한다.
- 결과 중복 제거, 상세 보강, 지원 상태 판정과 저장을 조율한다.
- 특정 상세 공고의 실패를 전체 검색 실패와 분리한다.

`CompanySearchService`:

- 로컬 Company Repository 검색을 항상 지원한다.
- 상세 원격 검색은 권한 설정이 있을 때만 Provider에 위임한다.
- 회사 ID 기준 병합과 현재 채용공고 연결을 담당한다.

`JobSearchProvider`:

```python
class JobSearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def search(
        self,
        request: JobSearchRequest,
        context: JobSearchContext,
    ) -> JobSearchResult: ...
```

`CompanySearchProvider`:

```python
class CompanySearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def search(
        self,
        request: CompanySearchRequest,
        context: CompanySearchContext,
    ) -> CompanySearchResult: ...

    async def get(
        self,
        company_id: str,
        context: CompanySearchContext,
    ) -> CompanyProfile: ...
```

`JobKoreaSearchAdapter`:

- 잡코리아 채용목록 내부 검색 UI를 조작한다.
- 결과 갱신을 검증하고 화면에 표시된 공고만 추출한다.
- 공고 ID를 기준으로 상세 방문 대상의 중복을 제거한다.
- 공유 Playwright Browser를 사용하되 작업별 BrowserContext를 격리한다.

`JobKoreaJobExtractor`:

- 목록 행, 상세 모집요강, JD와 지원정보를 파싱한다.
- HTML과 허용된 iframe을 우선하고, 이미지형 JD는 OCR에 위임한다.

`OcrProvider`:

- OCR 엔진을 교체할 수 있는 Port다.
- 기본 Adapter는 Tesseract 한국어·영어 조합을 사용한다.
- OCR 원문, 평균 신뢰도와 저신뢰 경고를 보존한다.

`SkillTaxonomy`:

- YAML 설정의 기술명과 별칭을 로드한다.
- JD에 직접 등장한 기술만 근거 문구와 함께 정규화한다.
- 필수, 우대, 단순 언급의 출처 섹션을 보존한다.

## 4. MCP 도구

### 4.1 `search_jobs`

입력 예시:

```json
{
  "site": "jobkorea",
  "keyword": "데이터 엔지니어",
  "location": ["서울"],
  "experience": ["신입", "1~3년"],
  "employment_type": ["정규직"],
  "max_results": 20
}
```

`keyword`는 런타임 문자열이며 특정 직무에 고정하지 않는다. 지역, 경력, 고용형태도
빈 목록을 허용한다. MCP Tool은 Pydantic 검증, Application Service 호출과 결과
직렬화만 담당한다.

요청 제한은 다음과 같다.

- `keyword`: 공백 제거 후 1~200자
- `location`, `experience`, `employment_type`: 각각 최대 20개, 항목당 1~100자
- 잡코리아 UI가 제공하지 않는 필터 값: 네트워크 요청 전에 구조화된 validation 오류
- `max_results`: 기본 20, 요청 모델 최대 100, 운영자 설정으로 더 낮출 수 있음

### 4.2 `search_companies`

입력 예시:

```json
{
  "company_name": "카카오",
  "max_results": 10,
  "include_details": false
}
```

`company_name`은 공백 제거 후 1~200자이며 `max_results`는 기본 10, 최대 100이다.

기본값은 로컬 Repository 검색이다. `include_details=true`는 상세정보 권한과
Authorized Provider가 모두 구성된 경우에만 허용한다.

### 4.3 `get_company`

입력 예시:

```json
{
  "company_id": "12345",
  "include_details": true
}
```

권한이 없을 때 최소 요약은 반환할 수 있으나 상세 원격 조회는 수행하지 않는다.

## 5. 데이터 계약

### 5.1 채용공고

```json
{
  "posting_id": "49471396",
  "site": "jobkorea",
  "title": "데이터 엔지니어",
  "company": {
    "company_id": "12345",
    "name": "회사명",
    "industry": "IT·정보통신",
    "company_type": "중견기업",
    "source_url": "https://www.jobkorea.co.kr/company/12345"
  },
  "employment": {
    "type": ["정규직"],
    "experience": "경력 3년 이상",
    "education": "학력무관",
    "location": "서울 강남구",
    "salary": "회사 내규에 따름",
    "headcount": "○명"
  },
  "application": {
    "started_at": "2026-08-01",
    "deadline_at": "2026-08-31",
    "deadline_type": "FIXED",
    "status": "OPEN",
    "is_applicable": true,
    "method": ["홈페이지 지원"],
    "apply_url": "https://example.com/apply",
    "status_reason": "검색 목록 노출 및 마감일 이전"
  },
  "jd": {
    "summary": "직무 요약",
    "responsibilities": [],
    "required_qualifications": [],
    "preferred_qualifications": [],
    "benefits": [],
    "raw_text": "정제 전 JD 전체 본문",
    "source_type": "HTML",
    "ocr_confidence": null
  },
  "tech_stack": [
    {
      "name": "Apache Spark",
      "normalized_name": "spark",
      "category": "data_processing",
      "requirement": "REQUIRED",
      "evidence": "Spark 기반 데이터 파이프라인 개발 경험"
    }
  ],
  "source_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/49471396",
  "collected_at": "2026-08-06T00:00:00+09:00",
  "warnings": []
}
```

### 5.2 지원 상태

지원 상태는 `SCHEDULED`, `OPEN`, `OPEN_ROLLING`, `CLOSED`, `UNKNOWN` 중 하나다.

| 조건 | 상태 | 지원 가능 |
|---|---|---:|
| 상세 페이지에 마감 표시 존재 | `CLOSED` | 아니요 |
| 시작일이 현재보다 이후 | `SCHEDULED` | 아니요 |
| 고정 마감일 이전이며 내부 검색에 노출 | `OPEN` | 예 |
| 채용 시 마감 또는 상시채용이며 내부 검색에 노출 | `OPEN_ROLLING` | 예 |
| 날짜 또는 화면 상태 근거 부족 | `UNKNOWN` | 아니요 |

`is_applicable=true`는 `OPEN`과 `OPEN_ROLLING`일 때만 허용한다. 날짜 계산은
`Asia/Seoul` 기준 날짜로 수행하고 판정 근거를 `status_reason`에 기록한다.

### 5.3 JD와 OCR

JD 추출 순서는 다음과 같다.

1. HTML의 주요 업무, 자격요건, 우대사항과 복리후생 영역을 찾는다.
2. 허용된 iframe 안에 있는 동일 영역을 찾는다.
3. 정규화된 텍스트가 200자 미만이거나 JD 섹션 제목과 두 개 이상의 항목을 모두
   찾지 못했고 JD 이미지가 있으면 OCR을 실행한다.
4. OCR 결과를 제목별 섹션으로 나눈다.
5. 원문, 정제 결과, OCR 신뢰도와 경고를 저장한다.

OCR 신뢰도는 0~1 범위로 정규화하고 0.70 미만이면 저신뢰 경고를 추가한다. 사용
가능한 HTML JD가 없고 OCR도 실패하거나 50자 미만의 결과만 생성하면 그 공고를
`items`에서 제외하고 `JD_IMAGE_OCR_FAILED` 페이지 실패로 기록한다. 사용 가능한
본문이 있으나 일부 이미지 OCR만 실패한 경우에는 공고를 반환하고 경고를 추가한다.
어느 경우에도 내용을 추측하지 않으며 원본 진단 이미지를 보존한다.

### 5.4 기술 스택

기술 스택은 YAML taxonomy로 정규화한다.

```yaml
python:
  aliases: [Python, 파이썬]
  category: programming_language
spark:
  aliases: [Spark, Apache Spark, PySpark]
  category: data_processing
airflow:
  aliases: [Airflow, Apache Airflow]
  category: orchestration
kafka:
  aliases: [Kafka, Apache Kafka]
  category: messaging
```

- `required_qualifications`에서 발견하면 `REQUIRED`다.
- `preferred_qualifications`에서 발견하면 `PREFERRED`다.
- 다른 JD 영역에서 발견하면 `MENTIONED`다.
- 근거 문자열이 없는 기술은 결과에 추가하지 않는다.
- 대소문자, 기호와 한글 별칭만 정규화하며 문맥에 없는 기술을 추론하지 않는다.

### 5.5 회사 정보

```json
{
  "company_id": "12345",
  "name": "회사명",
  "details_authorized": true,
  "industry": "IT·정보통신",
  "company_type": "중견기업",
  "employee_count": 100,
  "founded_at": "2000-01-01",
  "representative": "대표자",
  "capital": "자본금",
  "revenue": "매출액",
  "main_business": "주요사업",
  "address": "주소",
  "website": "https://example.com",
  "description": "기업소개",
  "benefits": [],
  "active_job_count": 0,
  "active_jobs": [],
  "source_url": "https://www.jobkorea.co.kr/company/12345",
  "collected_at": "2026-08-06T00:00:00+09:00"
}
```

권한이 없는 응답에서는 상세 필드를 `null` 또는 빈 목록으로 반환하고
`details_authorized=false`를 명시한다.

## 6. 검색 데이터 흐름

1. MCP Tool이 `JobSearchRequest`를 검증한다.
2. `JobSearchService`가 JobKorea Provider를 선택한다.
3. 작업별 BrowserContext로 `/recruit/joblist`에 접속한다.
4. 후보 Locator 중 존재, 표시, 활성화와 유일성을 만족하는 입력 요소를 선택한다.
5. 키워드와 선택 필터를 UI에 입력하고 검색을 실행한다.
6. 결과 건수, 목록 DOM, 적용 조건 중 두 가지 이상의 변경으로 검색 완료를 검증한다.
7. 화면에 표시된 공고 행과 ID를 추출한다.
8. 공고 ID로 중복을 제거하고 `max_results`까지 상세 페이지를 방문한다.
9. 상세 extractor가 고용조건, 지원기간과 JD를 보강한다.
10. 텍스트가 부족한 이미지형 JD에 OCR을 적용한다.
11. 지원 상태를 판정하고 기술 스택을 근거 문구와 함께 정규화한다.
12. 회사 요약과 현재 공고를 Repository에 upsert한다.
13. 검색 결과와 페이지 단위 실패를 함께 반환하고 저장한다.

Locator 우선순위는 role, label, placeholder, 안정적인 name/id/data-testid, CSS 순서다.
`nth-child`는 사용하지 않는다.

## 7. 오류와 부분 성공

전체 검색을 종료하는 오류:

- `JOB_SEARCH_FAILED`
- `JOB_SEARCH_UI_CHANGED`
- `JOB_SEARCH_NOT_PERMITTED`
- `JOB_SEARCH_BLOCKED`
- 브라우저 작업 timeout

공고 또는 회사 단위 실패:

- `JOB_DETAIL_EXTRACTION_FAILED`
- `JD_EXTRACTION_FAILED`
- `JD_IMAGE_OCR_FAILED`
- `APPLICATION_STATUS_UNKNOWN`
- `COMPANY_NOT_FOUND`
- `COMPANY_DATA_UNAUTHORIZED`
- `COMPANY_EXTRACTION_FAILED`

일부 상세 페이지가 실패해도 성공한 공고는 반환한다. `UNKNOWN` 상태 공고는 결과에
포함할 수 있지만 `is_applicable=false`로 고정한다. CAPTCHA와 차단은 재시도하거나
우회하지 않는다. 일시적 5xx와 timeout만 최대 두 번 재시도하고, OCR는 이미지
전처리를 바꿔 한 번만 추가 시도한다.

진단 구조:

```text
data/failures/{job_id}/
├── error.json
├── search-page.html
├── search-screenshot.png
├── accessibility_snapshot.txt
├── network-endpoints.json
└── postings/
    └── {posting_id}/
        ├── error.json
        ├── detail-page.html
        ├── screenshot.png
        ├── jd-image.png
        └── ocr-output.txt
```

Python traceback, 쿠키, Authorization header, storage state와 인증정보는 MCP 응답,
로그와 Artifact에 기록하지 않는다.

## 8. 테스트 설계

### 8.1 로컬 테스트 사이트

```text
/test-site/jobs
/test-site/jobs/search
/test-site/jobs/detail/html
/test-site/jobs/detail/image
/test-site/jobs/detail/closed
/test-site/companies
/test-site/company/1
```

테스트 사이트는 동적 검색어, 검색 결과 없음, Locator 변형, HTML JD, 이미지 JD,
고정 마감, 상시채용, 마감공고, 회사 요약과 상세 권한 시나리오를 제공한다.

### 8.2 단위 테스트

- 채용·회사 검색 요청과 상한 검증
- 지원 상태와 Asia/Seoul 날짜 경계
- JD 섹션 분리와 HTML 우선/OCR fallback 선택
- OCR 신뢰도와 실패 경고
- 기술 별칭, 요구 수준, 근거 문구와 오탐 방지
- 회사 상세정보 권한 gate
- 회사 Repository 검색, ID 병합과 현재 공고 연결
- MCP Tool의 얇은 경계 검증
- 민감정보 마스킹

### 8.3 통합 테스트

- 동적 검색어로 내부 검색 UI 조작
- 검색 결과 없음과 결과 갱신 검증
- Locator fallback과 UI 변경 실패 Artifact
- 목록·상세 탐색과 중복 제거
- HTML 및 이미지형 JD 추출
- Tesseract 한국어·영어 OCR
- 기술 스택과 근거 문구 추출
- 접수기간 및 지원 상태 판정
- 회사 요약 연결과 상세 권한 gate
- 부분 성공, robots 비허용 경로와 접근 차단
- Docker 환경 OCR 실행

### 8.4 실사이트 opt-in 테스트

```bash
JOBKOREA_TEST_KEYWORD="데이터 엔지니어" \
RUN_JOBKOREA_LIVE_TESTS=1 \
uv run pytest -m jobkorea_live
```

`JOBKOREA_TEST_KEYWORD`는 임의의 문자열로 변경 가능하다. 실사이트 테스트는 최대
3건, 동시 실행 1, 요청 간격 2초 이상을 강제한다. 내부 검색 화면에서 같은 실행 중
관찰한 공고 ID와 Adapter 결과를 비교한다. 특정 회사명이나 결과 개수는 고정하지
않는다. robots 비허용 경로, CAPTCHA 또는 차단이 발견되면 우회 없이 중단한다.

## 9. 완료 기준

1. 호출자가 전달한 임의의 검색어를 사용하고 코드에 직무를 하드코딩하지 않는다.
2. 반환된 공고 ID가 같은 실행의 잡코리아 내부 검색 목록과 일치한다.
3. 외부 검색엔진과 검색엔진 캐시를 사용하지 않는다.
4. 각 성공 공고에 JD, 접수기간, 지원 상태와 판정 근거가 포함된다.
5. 명시된 기술 스택에 요구 수준과 JD 근거 문구가 포함된다.
6. HTML 및 이미지형 JD를 지원하고 OCR 불확실성을 숨기지 않는다.
7. 회사 요약과 현재 채용공고를 연결한다.
8. 승인된 Provider가 구성된 경우 회사 상세 검색을 제공한다.
9. 권한이 없으면 회사 상세 원격 수집을 실행하지 않는다.
10. 마감·비노출·상태 불명 공고를 지원 가능 공고로 반환하지 않는다.
11. 부분 실패와 전체 실패가 구조화되고 필요한 진단 Artifact가 생성된다.
12. Ruff, mypy, 기본 pytest, 통합 pytest와 Docker OCR 검증이 모두 통과한다.

## 10. 범위 밖 항목

- 잡코리아 로그인과 사용자 세션 자동화
- 관심공고 저장, 입사지원과 이력서 제출
- CAPTCHA, 접근 차단과 rate limit 우회
- 외부 검색엔진을 이용한 공고 발견
- 권한 없는 회사 상세정보 원격 수집 또는 재배포
- JD에 없는 기술 스택의 추론
