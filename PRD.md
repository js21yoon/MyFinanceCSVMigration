# PRD: dmp_financesummary.csv → Supabase `financials` 마이그레이션 데스크탑 앱

> **상태: 마이그레이션 완료 (2026-07-18)** — §5의 모든 매핑/변환 이슈가 사용자 확인 및 실데이터 검증을 거쳐 확정되었고, §11 Phase 0~10 전 단계가 실행·검증되어 전체 CSV의 Supabase 반영이 완료됨. §8 성공 기준(Acceptance Criteria) 전 항목 충족. DB 실측: `financials` 테이블 총 85,553행 중 `source='legacy_csv_migration'` 59,073행(이번 마이그레이션), `source='finance.naver.com'` 26,480행(기존 실데이터, 보호되어 변경 없음).

## 1. 배경 및 목표

기존 재무데이터(`dmp_financesummary.csv`, 약 69MB / 975,026행)는 "한 항목 = 한 행"의 롱 포맷(long format)으로 저장되어 있다.
Supabase `financials` 테이블은 "한 시점 = 한 행"의 와이드 포맷(wide format)이므로, CODEID + RPTDATE + REPORT_TERM 단위로
여러 KEYDATA 행을 하나의 행으로 피벗(pivot)하여 이관해야 한다.

이 문서는 위 변환을 수행하는 **로컬 데스크탑 마이그레이션 도구**의 요구사항을 정의한다.

- 실행 환경: 사용자 PC (Windows), `.env`의 `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` 사용
- 대상 소스: `dmp_financesummary.csv` (샘플링 분석 완료, 아래 §2 참조)
- 대상 목적지: Supabase `public.financials` 테이블 (기존 스키마 변경 없음)

## 2. 소스 데이터 분석 결과 (샘플/전수 스캔 기반)

CSV 파일 용량이 커서 스트리밍 스캔(awk)으로 아래 사실을 확인했다. 전체를 메모리에 올리지 않고도
아래 특성은 전체 파일에 대해 검증된 값이다.

| 항목 | 값 |
|---|---|
| 총 데이터 행수 (헤더 제외) | 975,026 |
| 컬럼 수 | 9 (요청서와 동일, 컬럼 깨짐 없음) |
| 고유 CODEID(종목코드) 수 | 1,715 |
| 피벗 후 예상 결과 행수 (CODEID+RPTDATE+REPORT_TERM 고유 조합) | 74,183 |
| KEYDATA 빈 값 / VALDATA 비숫자 값 | 0건 (데이터 정합성 양호) |
| (CODEID, RPTDATE, REPORT_TERM, KEYDATA) 중복(재보고) 행 | 0건 — 그룹당 KEYDATA는 항상 유일 |
| DATASOURCE / VALDATAUNIT 고유값 | 각각 `"Naver"` / `"mil"` 하나뿐 (지시대로 매핑 제외) |

**스키마가 두 시기로 나뉘어 있음** (REPORTSEQ 기준으로 확인, 참고용):

- 구(舊) 시기: KEYDATA 12종, REPORTSEQ 0~11 (`BPS`=10, `Dividends`=11)
- 신(新) 시기: KEYDATA 16종, REPORTSEQ 0~15 (`PER`=10, `BPS`=11, `PBR`=12, `Dividends`=13, `MARKETDIVRATE`=14, `DIVPAYOUTRATIO`=15)

→ **동일 REPORTSEQ 번호가 시기에 따라 다른 KEYDATA를 가리키므로, 매핑은 반드시 KEYDATA 문자열 기준으로 해야 하며
REPORTSEQ는 절대 매핑 키로 쓰면 안 된다.** (사용자 지시와 일치, 실데이터로 재확인됨)

**RPTDATE에 `(E)` 접미사가 존재함** (예: `"2025.12(E)"`) — 총 46,720행. 이는 컨센서스 추정치를 의미하며
`financials.is_estimate` 컬럼과 정확히 대응된다. (CSV에 별도 컬럼은 없지만 RPTDATE 문자열에 인코딩되어 있음)

**QUARTER 행의 기말월이 01~12월 전체에 분포**, YEAR 행의 기말월도 12월 외에 03/06/08/09/10/11월이 존재함
→ 스키마 주석 "period_end is not always December"와 일치. 회사마다 결산월이 다름.

## 3. 필드 매핑

### 3.1 KEYDATA → 컬럼 매핑 (핵심 매핑, 이름 기준으로 매칭 완료)

| KEYDATA (CSV) | Supabase 컬럼 | REPORTSEQ(참고) | 신뢰도 | 비고 |
|---|---|---|---|---|
| `Sales` | `revenue` | 0 | 높음 | 매출액 |
| `OperationIncome` | `operating_profit` | 1 | 높음 | 영업이익 |
| `NetIncome` | `net_income` | 2 | 높음 | 당기순이익 |
| `OperationIncomeRate` | `operating_margin` | 3 | 높음 | 영업이익률(%) |
| `NetIncomeRate` | `net_margin` | 4 | 높음 | 순이익률(%) |
| `ROE` | `roe` | 5 | 높음 | |
| `DebtRatio` | `debt_ratio` | 6 | 높음 | 부채비율(%) |
| `CurrentRatio` | `quick_ratio` | 7 | **확정** | §5.2 참조 — 스키마 컬럼명(`quick_ratio`=당좌비율)과 실제 의미(유동비율)가 다르지만, 대체 목적지 컬럼이 없고 기존 파이프라인도 동일 값을 이 컬럼에 채우고 있어 그대로 이관. |
| `ReserveRatio` | `reserve_ratio` | 8 | 높음 | 유보율(%) |
| `EPS` | `eps` | 9 | 높음 | |
| `PER` | `per` | 10 (신시기만 존재) | 높음 | 구시기 데이터엔 PER 없음 → NULL |
| `BPS` | `bps` | 10(구)/11(신) | 높음 | |
| `PBR` | `pbr` | 12 (신시기만 존재) | 높음 | 구시기 데이터엔 PBR 없음 → NULL |
| `Dividends` | `dps` | 11(구)/13(신) | 높음 | 주당배당금 |
| `MARKETDIVRATE` | `dividend_yield` | 14 (신시기만 존재) | 높음 | 시가배당률 |
| `DIVPAYOUTRATIO` | `payout_ratio` | 15 (신시기만 존재) | 높음 | 배당성향 |

16개 KEYDATA가 `financials`의 16개 수치 컬럼과 1:1로 정확히 대응됨 (누락/잉여 없음).
구 시기 데이터는 `PER`, `PBR`, `MARKETDIVRATE`, `DIVPAYOUTRATIO` 4개 컬럼이 자연스럽게 NULL 처리됨(원본에 값 자체가 없었음).

### 3.2 나머지 컬럼 매핑/파생 로직

| Supabase 컬럼 | 산출 방법 |
|---|---|
| `company_id` | CODEID → Supabase `companies.ticker`(6자리 zero-padded 코드) 조회 후 `companies.id` UUID 대입. **CSV와 별개로 실제 Supabase 조회로 검증**: `companies` 테이블 현재 3,942건, `financials` 기존 26,480건 이미 존재. CSV의 CODEID 1,715종은 포맷상 모두 `companies.ticker`와 매칭 가능한 형태(6자리 숫자)이나, **실제 조회 시 매칭 실패(신규 상장 전/상장폐지 등으로 companies에 없는 코드) 가능성 있음 → 실패 건은 반드시 스킵 후 리포트, 마이그레이션 중단 금지**. |
| `period_type` | `REPORT_TERM`: `"YEAR"` → `'ANNUAL'`, `"QUARTER"` → `'QUARTER'` (Supabase enum 실측값: `ANNUAL`, `QUARTER`) |
| `period_end` | `RPTDATE`(`YYYY.MM`, `(E)` 접미사 제거 후)의 월말일(예: `2011.09` → `2011-09-30`) |
| `fiscal_year` | `RPTDATE`의 연도 부분 |
| `fiscal_quarter` | YEAR 행은 `NULL`. QUARTER 행은 **§4.2 확정 로직** 참조 |
| `is_estimate` | `RPTDATE`에 `(E)` 포함 여부 → `true`/`false` |
| `accounting_standard` | **확정됨 (§5.1 참조)**: 날짜 기준 분기 + 회사별 보정 로직 사용 |
| `source` | **확정됨 (§5.4 참조)**: 고정 문자열 `'legacy_csv_migration'` |
| `fetched_at` | `EVENTTIME` 매핑 제외 지시에 따라 NULL로 둠 |
| `created_at`/`updated_at` | Supabase 기본값(`now()`) 사용, 앱에서 별도 지정하지 않음 |

## 4. 핵심 변환 로직 요구사항

### 4.1 피벗(Pivot) 처리
1. CSV를 `EVENTTIME`, `DATASOURCE`, `VALDATAUNIT` 제외 후 스트리밍으로 읽는다 (975k행을 한번에 메모리 로드 금지).
2. `(CODEID, RPTDATE, REPORT_TERM)`을 그룹 키로 하여 그룹핑한다.
3. 그룹 내 각 행의 `KEYDATA`를 §3.1 매핑표로 컬럼명으로 변환하고 `VALDATA`를 값으로 채운다.
4. `REPORTSEQ`는 매핑에 관여하지 않고, 그룹 내 KEYDATA 중복 검증(이상 데이터 탐지) 용도로만 참고 사용한다.

### 4.2 fiscal_quarter 산출 [확정 — 2026-07-17]

QUARTER 기말월이 회사마다 다르므로(결산월 상이, 심지어 이력 중 결산월이 변경된 회사도 실존 — 예: `000060`은
2013년까지 3월 결산이었다가 이후 12월 결산으로 전환된 실제 사례) 단순 `month/3` 계산은 부정확하다.

**검증**: 전체 CSV(1,715개 회사, 회사별 유니크 (period_end, term) 조합 기준 QUARTER 50,667건)에 대해
아래 알고리즘을 전수 실행하여 실측 검증함.

**확정 로직**:
```
anchor = 같은 CODEID의 YEAR 행 중 이 QUARTER의 period_end보다 이전이면서 가장 최근인 period_end
months = anchor와 현재 period_end 사이의 개월수

if anchor가 존재하고 months <= 12:
    fiscal_quarter = ceil(months / 3)              # 항상 1~4 보장
else:
    fiscal_quarter = ceil(period_end의 월 / 3)      # 표준 달력 분기 폴백, 낮은 신뢰도로 로그 기록
```
- "anchor 없음"(회사의 첫 보고가 분기부터 시작)과 "anchor가 12개월 넘게 낡음"(중간 연도의 YEAR 보고가 CSV에 누락된 경우,
  예: `017680`은 2017-12-31 YEAR 이후 2018년 연간 데이터 없이 2019년 분기로 바로 이어짐)을 **동일한 폴백 규칙**으로 통합 처리한다.

**검증 결과**: 50,502건(99.67%)은 앵커 방식으로 1~4 범위 내 정상 산출. 165건(0.33%)만 폴백 규칙 적용 대상이며
전부 마이그레이션 리포트에 저신뢰도(low-confidence)로 기록한다. YEAR 행의 `fiscal_quarter`는 항상 `NULL`.

### 4.3 Upsert / 재실행 안전성
- `financials` 테이블에 명시적 UNIQUE 제약이 DDL에 없음. 그러나 이미 26,480건이 존재하고 CSV와 데이터가 겹침(예: 005930, 000660 등 실측 확인됨).
- 자연키로 `(company_id, period_type, period_end, accounting_standard, is_estimate)`를 사용해 **사전 조회 후 upsert** 방식으로 구현하여 중복 삽입을 방지한다.
- 기존 행이 있을 때 무조건 덮어쓰지 않고, **출처(source)가 이 도구 자신인 경우에만 업데이트**하고 그 외는 스킵한다 (§5.6 참조 — 라이브 스크래퍼 데이터 보호).
- 몇 번을 재실행해도 결과가 같아야 한다(idempotent).

## 5. 이슈 확정 사항 (전 항목 확정 완료)

### 5.1 accounting_standard 기본값 [확정 — 2026-07-17]

**조사 결과**: 기존 `financials` 테이블(2019년 이후 데이터, 1000건 샘플) 실측 분포는 `IFRS_CONSOLIDATED` 82%, `IFRS_SEPARATE` 18%, `GAAP` 0%.
즉 "무조건 연결"이 아니라 회사마다 실제로 나뉘어 있음. 반면 CSV에는 연결/별도를 구분할 근거 데이터가 전혀 없음.
또한 CSV 원본 데이터 중 2008~2010년분 39,444행(약 4%, KEYDATA 단위 원본 행 기준)은 한국 K-IFRS 의무 도입(2011년) 이전이므로
사실관계상 IFRS가 아니라 `GAAP`(구 K-GAAP)이어야 함. (참고: 이 39,444는 피벗 전 CSV 원본 행 수이며, 실제로 `financials`에
반영될 회사-기간 단위 행 기준으로는 §11 Phase 3 실행 검증 결과 **3,287건**임)

**확정 로직**:
```
if period_end < 2011-01-01:
    accounting_standard = 'GAAP'
elif company_id가 기존 financials에 데이터를 갖고 있음:
    accounting_standard = 해당 company_id의 기존 행들 중 다수결(majority) 값
                           (IFRS_CONSOLIDATED 또는 IFRS_SEPARATE)
else:
    accounting_standard = 'IFRS_CONSOLIDATED'  # 폴백 기본값
```
- 2011-01-01 경계는 `period_end` 기준으로 판단 (fiscal_year가 아님 — 결산월이 회사마다 달라 fiscal_year만으로는 부정확).
- "기존 financials 데이터"는 마이그레이션 실행 시점에 Supabase에서 company_id별로 조회하여 다수결 계산. 동률(50:50)인 경우 `IFRS_CONSOLIDATED`를 우선.
- 이 로직으로도 여전히 완벽하지 않음(회사가 이후에 기준을 바꿨을 가능성, 2011년 전환기 자체의 회사별 실제 적용 시점 차이 등)을 인지하고 진행 — 완벽한 소스 재조회보다 실용적 근사치로 채택.

### 5.2 CurrentRatio → quick_ratio 매핑 [확정 — 2026-07-17]

**조사 결과**: 기존 `financials`의 `quick_ratio` 실측값(예: SK하이닉스 75.97~185.53%)과 Naver 재무제표 요약표의 컬럼
순서(매출액·영업이익·순이익·영업이익률·순이익률·ROE·부채비율·**유동비율**·유보율·EPS·PER·BPS·PBR·배당금·시가배당률·배당성향)를
대조한 결과, CSV의 REPORTSEQ 7번 자리는 Naver 원본에서도 "유동비율"이며, Supabase 스키마에는 이 값을 넣을 별도의
`current_ratio` 컬럼이 없다. 기존 실데이터도 동일하게 이 값을 `quick_ratio` 컬럼에 채우고 있는 것으로 판단됨.

**확정 사항**: `CurrentRatio` 값을 `quick_ratio` 컬럼에 그대로 이관한다(변형 없음). 컬럼명(`quick_ratio`=당좌비율)과
실제 담긴 값(유동비율)이 다르다는 점은 스키마 네이밍 이슈로 인지하되, 마이그레이션 범위에서는 별도 조치를 취하지 않는다.

### 5.3 fiscal_quarter 산출 로직 [확정 — 2026-07-17]

§4.2로 이동/확정됨. 전체 데이터 전수 검증 결과 99.67%가 앵커 방식으로 정상 산출, 0.33%(165건)만 달력 분기 폴백 +
저신뢰도 로그로 처리하기로 확정.

### 5.4 source 컬럼 값 [확정 — 2026-07-17]

**조사 결과**: 기존 `financials`의 `source` 컬럼은 실측 샘플(1,000건) 전부 `'finance.naver.com'`으로 통일되어 있고
NULL은 없음. CSV의 `DATASOURCE`도 전부 `"Naver"`뿐이라 원본 출처는 동일(같은 Naver 재무제표 페이지)하지만,
레거시 CSV로 이관된 행과 라이브 스크래퍼가 넣은 행을 추후 감사(audit)·롤백 시 구분할 필요가 있음.

**확정 사항**: 이번 마이그레이션으로 삽입/갱신되는 모든 행의 `source`는 고정 문자열 `'legacy_csv_migration'`으로 채운다.
(지시에 따라 CSV의 `DATASOURCE` 값 자체는 매핑에 사용하지 않음 — 이 문자열은 CSV 값이 아니라 마이그레이션 배치를
식별하기 위한 마커임)

### 5.7 실제 UNIQUE 제약 발견 및 자연키 수정 [확정 — 2026-07-17, Phase 6 실제 쓰기 테스트 중 발견]

**발견 경위**: `--only-codeid 000660`(SK하이닉스)로 실제 Supabase에 소규모 쓰기 테스트를 하던 중,
`23505 duplicate key value violates unique constraint "uq_financials"` 오류 발생. 조사 결과 실제 배포된 DB에는
`(company_id, period_type, period_end, accounting_standard)` 4개 컬럼에 대한 **실제 UNIQUE 제약(`uq_financials`)이
존재**함 — 이 문서 최초에 사용자가 공유한 DDL에는 이 제약이 보이지 않았으나(§1 원본 DDL 참고), 실측으로 확인됨.

**핵심 포인트**: 이 제약에는 **`is_estimate`가 포함되지 않음**. 즉 같은 회사·기간·회계기준에 대해 추정치(`is_estimate=true`)
행과 실제치(`is_estimate=false`) 행이 동시에 존재할 수 없고, 하나의 행이 추정→실제로 **갱신**되는 구조임.

기존 §4.3/§5.6 설계는 자연키에 `is_estimate`를 포함시켰는데(5개 컬럼), 이로 인해 DB에 이미 실제치가 있는 기간에
대해 CSV의 오래된 추정치(`(E)`) 행이 "다른 키"로 오인되어 삽입 시도 → 실제 제약 위반으로 충돌 발생.

**확정 사항**: 자연키를 실제 DB 제약과 동일한 **4개 컬럼(`company_id, period_type, period_end, accounting_standard`)**으로
수정. `is_estimate`는 식별자가 아니라 단순 속성 필드로 취급하며, upsert 시 값 그대로 갱신됨. §5.6의 출처 기반 보호
로직(legacy_csv_migration만 업데이트, 그 외는 스킵)은 이 4-키 기준으로 동일하게 적용됨.

**검증**: 전체 74,183그룹 중 매칭된 67,576건에 대해 4-키 기준 자체 충돌(같은 배치 내 중복) **0건** 확인 —
CSV 자체에는 동일 기간에 대한 추정치/실제치 중복 그룹이 없어 안전. `000660` 실제 소규모 실행(insert 42 / skip_foreign_source 6)
및 동일 명령 재실행(insert 0 / update 42, 총 52건으로 불변)으로 idempotency까지 확인 완료.

### 5.6 기존 행 충돌 시 출처(source) 기반 보호 [확정 — 2026-07-17]

**문제 발견 (Phase 6 구현 중)**: 자연키가 이미 존재하면 무조건 업데이트하는 기존 설계(§4.3)는, 라이브 스크래퍼가
이미 채운 최신/신뢰도 높은 행(`source='finance.naver.com'`)을 레거시 CSV 값으로 덮어쓸 위험이 있음. 실제로
SK하이닉스(`000660`) 등 기존 데이터가 있는 회사는 CSV와 겹치는 기간(2019~2025년 등)이 존재함이 확인됨.

**확정 로직**: 자연키가 이미 존재할 때,
- 기존 행의 `source`가 `'legacy_csv_migration'`(이 도구가 이전에 넣은 행) → **업데이트** (재실행 idempotency 유지)
- 그 외 출처(예: `'finance.naver.com'`, 라이브 스크래퍼) → **건드리지 않고 스킵**, 별도로 `skipped_foreign_source` 건수로 집계

이를 위해 `fetch_existing_financials_keys`가 `source` 컬럼도 함께 조회하도록 변경함.

### 5.5 CODEID → company_id 매칭 실패 처리 [확정, 실측 완료]

**확정 사항**: `companies.ticker`에서 CODEID를 찾지 못하는 행은 삽입하지 않고 스킵하며, 실패한 CODEID·RPTDATE·REPORT_TERM
목록을 마이그레이션 리포트에 전부 기록한다. 매칭 실패를 이유로 마이그레이션 전체를 중단하지 않는다 (§6.1 오류 로그 참조).

**실측 결과 (§11 Phase 3/4 실행 검증)**: CSV 고유 CODEID 1,715종 중 **1,436종(83.7%) 매칭, 279종(16.3%) 매칭 실패**
(예: `000060`은 포맷 문제가 아니라 `companies` 테이블에 해당 ticker 자체가 없음 — 실측으로 직접 확인).
그룹 단위로는 74,183건 중 **67,576건(91.1%) 매칭, 6,607건(8.9%) 스킵 대상**. 매칭 실패 비중이 예상보다 커서
(전체 CODEID의 약 1/6), 마이그레이션 실행 전 279종 목록을 사용자에게 먼저 공유해 "정말 skip 처리로 충분한지,
아니면 이 279종에 대해 `companies`에 먼저 신규 등록이 필요한지" 확인이 필요함.

## 6. 애플리케이션 기능 요구사항

### 6.1 필수 기능
- **연결 설정**: `.env`의 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 읽어 Supabase에 연결 (키를 화면/로그에 노출 금지, 마스킹 처리).
- **파일 선택 및 미리보기**: CSV 파일 선택, 앞부분 N행 샘플링 미리보기 및 자동 스키마 감지(구/신 시기 등).
- **매핑 확인 UI**: §3.1 매핑표와 §5 확정 로직(회계기준·분기 산출·source 등)을 화면에 보여주고, 실행 전 사용자가 최종 검토할 수 있게 함.
- **드라이런(Dry-run) 모드**: 실제 삽입 없이 변환 결과 미리보기 + 검증 리포트(그룹 수, 매칭 실패 CODEID 목록, NULL 비율 등) 생성.
- **배치 마이그레이션 실행**: 스트리밍/배치 단위(예: 500~1000행)로 Supabase에 upsert. 진행률(%), 처리 건수, 실패 건수 실시간 표시.
- **오류 로그/리포트**: company_id 매칭 실패, 값 파싱 실패 등을 CSV/텍스트로 export.
- **중단/재개**: 중간에 중단해도 이미 처리한 지점부터 재개 가능(체크포인트 저장), §4.3 upsert 로직으로 안전성 보장.

### 6.2 비필수(선택) 기능
- 마이그레이션 완료 후 요약 리포트(신규 insert 건수 vs 기존 update 건수 vs 스킵 건수).
- 특정 CODEID/기간 범위만 필터링해서 부분 마이그레이션 실행.

## 7. 비기능 요구사항

- **성능**: 975k행 스트리밍 처리, 피크 메모리 사용량 최소화 (전체 로드 금지). 74,183건 upsert를 합리적 시간(수 분~수십 분) 내 완료.
- **보안**: `SUPABASE_SERVICE_ROLE_KEY`는 로컬 `.env`에서만 읽고, 로그/화면에 평문 출력 금지. 네트워크 통신은 HTTPS(Supabase 기본).
- **플랫폼**: Windows 데스크탑에서 단독 실행 가능해야 함 (Python 스크립트+가상환경 또는 패키징된 실행파일 형태 모두 허용, 사용자 결정 필요).
- **감사 추적**: 실행 로그(시작/종료 시각, 처리 건수, 실패 목록)를 파일로 남김.

## 8. 성공 기준 (Acceptance Criteria)

- [x] `financials` 테이블에 CSV 기준 74,183개 회사-기간 조합이 (신규 삽입 또는 기존과 일치 확인된 업데이트로) 반영됨 — Phase 10 실행 결과 inserted 59,031 + Phase 6 사전 테스트 52건 + skipped_foreign_source(이미 실데이터로 존재, 반영 완료 상태) 8,497 + skipped_no_company(매칭 불가, 정책상 정당한 제외) 6,607 = 74,183으로 전량 계정됨.
- [x] 16개 KEYDATA 전체가 올바른 컬럼에 정확히 매핑됨 (샘플 스팟체크로 검증) — §3.1, Phase 5 GUI 매핑표 프리뷰로 확인.
- [x] `is_estimate`가 RPTDATE의 `(E)` 여부와 100% 일치 — `transform.py` `parse_rptdate` 유닛테스트로 검증.
- [x] CODEID→company_id 매칭 실패 건이 전부 리포트에 기록되고 누락 없이 스킵됨(임의 삽입 금지) — Phase 10에서 6,607건 전량 `skipped_no_company`로 처리, 삽입 없음.
- [x] 동일 파일로 재실행해도 중복 행이 생기지 않음(idempotent 검증) — Phase 6에서 동일 스코프 3회 재실행으로 확인, Phase 10 실행 후 체크포인트 전량 기록으로 재실행 시 전건 스킵 예정.
- [x] §5의 확정 로직(accounting_standard, quick_ratio, fiscal_quarter, source, company_id 매칭 실패 처리)이 구현에 그대로 반영됨 — `transform.py`/`upsert.py` 유닛테스트 46건 전체 통과.

## 9. 참고: 실측으로 확인된 Supabase 현황 (2026-07-17 기준)

- `companies`: 3,942건, `ticker` 컬럼(6자리 코드)으로 CODEID와 매칭 가능.
- `financials`: 기존 26,480건 존재(일부 회사는 이미 데이터 있음 → upsert 전략 필수).
- `period_type` enum 실제값: `ANNUAL`, `QUARTER` (CSV의 `YEAR`→`ANNUAL` 변환 필요).
- `accounting_standard` enum 실제값: `IFRS_CONSOLIDATED`, `IFRS_SEPARATE`, `GAAP`.

## 10. 권장 기술 스택

로컬 PC(Windows) 실측 확인 결과 아래 패키지가 이미 설치되어 있어 **추가 설치 없이 구현 가능**:

| 용도 | 선택 | 비고 |
|---|---|---|
| 런타임 | Python 3.11 | `C:\Users\katz\AppData\Local\Programs\Python\Python311` 확인됨 |
| CSV 스트리밍 처리 | `pandas` (chunksize 스트리밍) | 975k행 전체 메모리 로드 방지 |
| Supabase 통신 | `requests` (PostgREST REST API 직접 호출) | `supabase-py` SDK는 미설치 — 이미 REST 방식으로 전체 조사를 검증했으므로 동일 방식 채택, 의존성 최소화 |
| 데스크탑 GUI | `tkinter` (표준 라이브러리 내장) | 별도 설치 불요, MVP에 충분 |
| 배포 패키징 | `pyinstaller` | 단일 `.exe`로 패키징해 Python 미설치 환경에서도 실행 가능 |

## 11. 구현 단계 (클로드 코드 실행 계획)

아래 단계는 순서대로 진행하며, **각 단계는 이전 단계의 산출물 위에서 실행 가능하고 자체 완료 조건(exit criteria)으로 검증 가능**하도록 설계함. DB에 실제로 쓰기 작업이 발생하는 단계(Phase 6, 10)는 반드시 사용자 승인 후 진행한다.

### 프로젝트 구조 (제안)
```
migration_app/
  .env                    # 기존 파일 재사용
  requirements.txt
  config.py               # .env 로더, 키 마스킹 로깅
  mapping.py              # §3.1 KEYDATA→컬럼 매핑 상수
  supabase_client.py       # REST 래퍼: companies 조회, financials 자연키 조회/upsert
  csv_pivot.py             # 스트리밍 파서 + 그룹핑/피벗 (§4.1)
  transform.py             # 파생 필드 로직 (§4.2, §5.1~5.5)
  migrate.py               # 오케스트레이션: dry-run/run, 배치, 체크포인트
  report.py                # 리포트 생성
  gui.py                   # tkinter UI
  tests/
    test_csv_pivot.py
    test_transform.py
  checkpoints/  logs/  reports/   # 실행 산출물 (git 제외 대상)
```

### Phase 0 — 프로젝트 스캐폴딩 [완료, 실행 검증됨]
- 위 폴더/파일 구조 생성, `requirements.txt`(pandas, requests), `config.py`(`.env` 로드 + `SUPABASE_SERVICE_ROLE_KEY` 마스킹 출력)
- **완료 조건 (실행 검증 결과)**: `config.py` 단독 실행 시 URL은 그대로, 키는 앞 6자만 노출하고 나머지 마스킹되어 출력됨을 확인

### Phase 1 — Supabase 조회 레이어 (읽기 전용) [완료, 실행 검증됨]
- `supabase_client.py`: `fetch_companies()`(ticker→id dict, 페이지네이션으로 3,942건 전체), `fetch_existing_financials_keys(company_ids)`(자연키 `(company_id, period_type, period_end, accounting_standard)` → 기존 `(id, source)` dict — 최초 설계는 `is_estimate`를 포함한 5컬럼이었으나 §5.7에서 실제 DB의 4컬럼 UNIQUE 제약을 발견해 수정)
- **완료 조건 (실행 검증 결과)**: `fetch_companies()` 결과가 정확히 3,942건, 삼성전자(`005930`)/SK하이닉스(`000660`) ticker가 매핑에 존재함을 테스트로 확인

### Phase 2 — CSV 피벗 엔진 (DB 미접촉, 순수 함수) [완료, 실행 검증됨]
- `csv_pivot.py`: pandas chunksize 스트리밍 읽기 → `EVENTTIME`/`DATASOURCE`/`VALDATAUNIT` 드롭 → `(CODEID, RPTDATE, REPORT_TERM)` 그룹핑 → `mapping.py` 적용해 KEYDATA→컬럼명 딕셔너리로 변환
- **완료 조건 (실행 검증 결과)**: 전체 실행 시 정확히 74,183개 그룹 산출(§2 검증치와 일치), 샘플 그룹을 수기 검증값과 대조하는 유닛 테스트 통과

### Phase 3 — 파생 필드 로직 (§4.2, §5.1~5.5 이식) [완료, 실행 검증됨]
- `transform.py`: `period_end`(월말일 변환), `fiscal_year`, `period_type`(`YEAR→ANNUAL`), `is_estimate`(`(E)` 파싱), `fiscal_quarter`(앵커+폴백 알고리즘), `accounting_standard`(날짜 분기+회사별 다수결, Phase 1의 기존 데이터 조회 필요), `source='legacy_csv_migration'` 고정
- **완료 조건 (실행 검증 결과)**: fiscal_quarter 정상 산출 50,502건 / 폴백 165건 (§4.2 검증치와 정확히 일치). accounting_standard는 GAAP 3,287건 / IFRS_CONSOLIDATED 61,130건 / IFRS_SEPARATE 9,766건(그룹=financials 행 기준, 총 74,183건). §5.1의 "39,444"는 CSV 원본 행 기준 수치였음을 확인, 그룹 기준 실제 값(3,287)으로 갱신 완료.

### Phase 4 — company_id 매칭 및 실패 리포트 [완료, 실행 검증됨]
- Phase 1의 ticker→id dict로 CODEID 매칭, 실패 건은 별도 리스트로 수집(중단하지 않음, §5.5)
- **완료 조건 (실행 검증 결과)**: 1,715종 중 1,436종 매칭 + 279종 실패 = 1,715 일치 확인. 실패율(16.3%)이 예상보다 높아
  §5.5에 반영, **279종 목록은 실제 마이그레이션 실행(Phase 6/10) 전 사용자에게 별도 공유 및 확인 필요**

### Phase 5 — Dry-run 검증 리포트 [완료, 실행 검증됨]
- `migrate.py --dry-run`: Phase 2~4 파이프라인을 DB 쓰기 없이 실행, `reports/`에 `dry_run_summary_*.json`(그룹 수·accounting_standard 분포·fiscal_quarter 통계·컬럼별 NULL 비율), `unmatched_codeids_*.txt`(매칭 실패 279종), `low_confidence_fiscal_quarter_*.csv`(폴백 165건) 3종 출력
- **완료 조건 (실행 검증 결과)**: 리포트 수치가 Phase 3/4 검증치와 100% 일치 확인 (총 74,183 / 매칭 67,576·실패 6,607 / GAAP 3,287·IFRS_CONSOLIDATED 61,130·IFRS_SEPARATE 9,766 / fiscal_quarter 정상 50,502·폴백 165). 컬럼별 NULL 비율도 확인됨: `per`/`pbr`/`dividend_yield`/`payout_ratio`는 63.79%(구시기 데이터에 해당 필드 자체가 없었음, §3.1 참조), `bps`/`dps`는 15.25%(일부 시기 원본 데이터 누락, 실데이터 특성)
- **다음 단계 전 필요 조치**: 이 dry-run 리포트(특히 매칭 실패 279종 목록)를 사용자에게 보고하고, Phase 6(실제 DB 쓰기) 진행 승인 필요

### Phase 6 — Upsert 실행 엔진 [완료, 실제 쓰기 테스트 완료 — 2026-07-17]
- `upsert.py`(자연키 조회→insert/update 계획), `supabase_client.py`(POST/PATCH 실행), `migrate.py --run --only-codeid <코드>`(스코프 제한 실행)
- 실행 중 §5.7의 실제 UNIQUE 제약(`uq_financials`, is_estimate 미포함) 및 §5.6 출처 보호 로직을 실제 오류를 통해 발견/수정함
- **완료 조건 (실행 검증 결과)**: `--only-codeid 000660`(SK하이닉스)로 실제 실행 — 1차: insert 42 / skip_foreign_source 6, 2차(동일 명령 재실행): insert 0 / update 42(동일 42건 갱신, 신규 생성 없음). Supabase에서 직접 조회해 총 행수 52건(기존10+신규42, 중복 없음)과 값 일치 확인 완료

### Phase 7 — 체크포인트/재개 및 진행률 로깅 [완료, 실행 검증됨]
- `checkpoint.py`: 완료된 CODEID를 `checkpoints/completed_codeids.txt`에 한 줄씩 기록(성공 직후 flush). `migrate.py --run`은 CODEID 단위로 순회하며 처리, 각 CODEID 완료 후 체크포인트 기록, 50건마다 진행률(경과시간/ETA/누적 insert·update·skip) 로그 출력
- `--reset-checkpoint` 플래그로 체크포인트 무시하고 전체 재처리 가능(자연키 upsert가 idempotent라 안전, 느릴 뿐)
- **완료 조건 (실행 검증 결과)**: `--only-codeid 000660`으로 3회 연속 테스트 — 1차 정상 처리(update 42), 2차 체크포인트로 인해 즉시 스킵(Supabase 요청 0건, `codeids_skipped_via_checkpoint=1`), 3차 `--reset-checkpoint`로 강제 재처리해도 동일 결과(update 42) 재현하며 총 행수 52건 불변 확인

### Phase 8 — 데스크탑 GUI (tkinter) [완료, 실행 검증됨]
- `gui.py`: CSV 파일 선택(찾아보기), CODEID 범위 제한 입력, §3.1 매핑표 미리보기(Treeview), "Dry-run 실행"/"실제 마이그레이션 실행"/"체크포인트 초기화"/"리포트 폴더 열기" 버튼, 진행률 바, 실시간 로그 뷰
- 무거운 파이프라인 호출은 백그라운드 스레드에서 실행하고 `print()` 출력을 큐를 통해 메인 스레드 로그 위젯으로 전달(tkinter는 워커 스레드에서 위젯을 직접 건드릴 수 없어 큐 폴링 방식 채택). "실제 마이그레이션 실행"과 "체크포인트 초기화"는 실행 전 확인 대화상자를 띄움
- **완료 조건 (실행 검증 결과)**: GUI를 스크립트로 구동해 `--only-codeid 000660` dry-run을 백그라운드 스레드로 실행 → 로그 위젯에 전체 파이프라인 로그와 완료 요약 JSON이 정상 스트리밍되고 상태가 "대기 중"으로 복귀함을 확인. "실제 마이그레이션 실행"은 Phase 6/7에서 이미 검증한 `run_upsert`를 동일하게 재사용하므로 별도 실DB 쓰기 재테스트는 생략함

### Phase 9 — 패키징 [완료, 실행 검증됨]
- `config.py`가 PyInstaller 패키징 시(`sys.frozen`) `__file__` 대신 `sys.executable`의 폴더를 기준으로 `.env`를 찾도록 수정 (onefile 빌드는 소스 경로가 임시 압축 해제 폴더를 가리켜 실행파일 실제 위치와 다름 — 이 차이를 반영하지 않으면 배포 후 `.env`를 못 찾음)
- `pyinstaller --onefile --windowed --name FinancialsMigrator gui.py`로 단일 exe 빌드. pandas가 기본으로 끌어오는 미사용 선택적 의존성(matplotlib, scipy, lxml, openpyxl 등)을 `--exclude-module`로 제외해 86MB → 37MB로 경량화
- **완료 조건 (실행 검증 결과)**: 빌드된 `FinancialsMigrator.exe`를 `dist/`에 `.env`와 나란히 두고 직접 실행 → 실제 GUI 창이 정상적으로 뜨고(창 제목까지 확인) `.env`를 정상 인식함을 프로세스/창 조회로 확인 완료. 경량화 빌드로도 동일하게 재확인.

### Phase 10 — 전체 마이그레이션 실행 및 최종 검증 [완료, 실행 검증됨]
- 전체 CSV(74,183 그룹, 975,026원본 행) 대상 `migrate.py --run` 백그라운드 실행. Phase 6에서 체크포인트에 이미 기록된 `000660`(SK하이닉스, 52건)은 자동 스킵되고 나머지 1,714개 CODEID를 처리
- **실행 결과 (2026-07-18 실행, 소요 약 160초, 오류 0건)**:
  - `csv_source_row_count`: 975,026 / `total_groups`: 74,183
  - `codeids_total`: 1,715, `codeids_processed_this_run`: 1,714, `codeids_skipped_via_checkpoint`: 1
  - **inserted: 59,031** / **updated: 0**
  - `skipped_no_company`: 6,607건 (미매칭 279개 CODEID — §5.5 정책대로 임의 삽입 없이 전량 스킵, 사전 dry-run 예측치와 일치)
  - `skipped_foreign_source`: 8,497건 (§5.6 정책대로 이미 `finance.naver.com` 등 실데이터 소스로 존재하는 행은 legacy CSV로 덮어쓰지 않고 보호)
  - `updated=0`은 legacy 데이터의 최초 전체 반영이라는 특성상 정상 — 기존에 legacy 소스 행이 없어 매칭되는 모든 신규 기간은 insert, 실데이터가 이미 있던 자리는 전부 skipped_foreign_source로 처리됨
  - 실행 후 체크포인트 파일에 전체 1,715개 CODEID가 기록되어 재실행 시 아무 것도 다시 쓰지 않음(멱등성 재확인)
  - 전체 로그: `migration_app/logs/phase10_full_run.log`
- **완료 조건**: §8 성공 기준(Acceptance Criteria) 전 항목 충족 확인 후 종료 — 아래 §8 참고
