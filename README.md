# dmp_financesummary.csv → Supabase `financials` 마이그레이션

레거시 long-format 재무 CSV(`dmp_financesummary.csv`, 회사-기간-지표 단위 975,026행)를
Supabase `financials` 테이블의 wide-format(회사-기간당 1행)으로 변환·적재하는 Windows 데스크탑 도구입니다.

전체 요구사항, 설계 결정, 실행 검증 결과는 [`PRD.md`](./PRD.md)를 참고하세요.

## 주요 기능

- CSV 스트리밍 피벗 (`CODEID`, `RPTDATE`, `REPORT_TERM` 기준 그룹핑, 전체 메모리 로드 없음)
- KEYDATA → Supabase 컬럼 매핑 (`migration_app/mapping.py`, 16개 지표)
- 파생 필드 산출: `period_type`, `fiscal_year`, `fiscal_quarter`(앵커+폴백 알고리즘), `is_estimate`, `accounting_standard`(날짜 분기 + 회사별 다수결)
- Dry-run 검증 리포트 (DB 쓰기 없이 매칭률/null 비율/신뢰도 통계 확인)
- 자연키 기반 idempotent upsert + 출처(source) 기반 보호 (기존 실데이터를 legacy CSV가 덮어쓰지 않음)
- CODEID 단위 체크포인트로 중단/재개 가능
- tkinter GUI 및 CLI 양쪽 지원

## 요구 사항

- Python 3.11+
- 표준 라이브러리 + `pandas`, `requests` (`migration_app/requirements.txt`)
- Supabase 프로젝트의 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 담은 `.env` 파일 (저장소에는 포함되지 않음, `migration_app/` 또는 프로젝트 루트에 직접 배치)

```bash
pip install -r migration_app/requirements.txt
```

## 사용법

### GUI

```bash
python migration_app/gui.py
```

CSV 파일 선택 → 매핑 미리보기 확인 → Dry-run 실행 → 리포트 검토 → 실제 마이그레이션 실행 순서로 진행합니다.

### CLI

```bash
# 검증만 (DB 쓰기 없음)
python migration_app/migrate.py --dry-run

# 특정 CODEID만 실행 (실제 DB 쓰기, 소규모 테스트에 권장)
python migration_app/migrate.py --run --only-codeid 000660

# 전체 실행
python migration_app/migrate.py --run

# 체크포인트 초기화 후 전체 재처리
python migration_app/migrate.py --run --reset-checkpoint
```

## 테스트

```bash
cd migration_app
python -m unittest discover tests
```

## 프로젝트 구조

```
migration_app/
  config.py           # .env 로더, 키 마스킹
  mapping.py           # KEYDATA -> 컬럼 매핑
  csv_pivot.py          # 스트리밍 파서 + 피벗
  transform.py          # 파생 필드 로직
  supabase_client.py    # PostgREST REST 래퍼
  upsert.py             # 자연키 upsert 계획/실행
  checkpoint.py         # CODEID 단위 재개 지점 관리
  report.py             # dry-run 리포트 생성
  migrate.py            # CLI 오케스트레이션
  gui.py                # tkinter 데스크탑 UI
  tests/                # unittest 스위트
```

## 보안 참고

`.env`, `checkpoints/`, `logs/`, `reports/`, 원본 CSV(`dmp_financesummary.csv`)는 `.gitignore`로 제외되어 있습니다.
`SUPABASE_SERVICE_ROLE_KEY`는 로그/화면에 절대 평문 노출되지 않으며, `config.py`가 마스킹해서만 출력합니다.
