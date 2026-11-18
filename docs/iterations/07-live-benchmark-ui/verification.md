# 7단계 검증 기록 — 로컬 준비·실행 서버 연결 (체크포인트 3)

- **상태:** 구현자 자체 실행 결과. U 5개·I 16개 TC를 테스트 이중물·격리 임시 프로세스로 자동화했다. 독립 코드 검증의 결함 2건을 고친 **현재 코드에서 47/47 통과**(6절). 2절의 44/44는 수정 전 스냅샷이다. 실제 Docker·MongoDB·`benchmark.py`·브라우저(E-001~003, I-017)와 코드 검토(R-001~003)는 **미실행**이며 독립 검토 판정도 없다.
- **기준:** [TC (test-cases.md)](test-cases.md), [구현 기록 (implementation.md)](implementation.md), [설계](design.md).
- **원자료(로컬, Git 제외):** `.agent/verification/mini-redis-i07-server/` — 단계별 RED/GREEN 로그, 최종 전체 로그 `08-final-full.log`, 기동 확인 `07-smoke.json`과 스크립트 `smoke_entrypoint.py`, 보호 파일 해시 `baseline-hashes.txt`·`final-hashes.txt`, 신규 파일 해시 `new-hashes.txt`.

## 1. 환경과 격리

- macOS 26.6.2, Python 3.14.5(`/opt/homebrew/bin/python3`), 저장소 HEAD `dbe9346` + 미커밋 작업 트리. pymongo 없이 실행(이중물 사용).
- Docker는 `FakeDocker`(메모리 또는 JSON 파일 공유 상태), MongoDB는 읽기 호출만 가진 `FakeReader`. 시드·측정기는 임시 디렉터리의 Python 스크립트로, 실제 `seed_mongo.py`·`benchmark.py`와 같은 CLI 형태(`--output`, `--mongo-uri`)만 흉내 낸다. 공유 기록·실행 디렉터리는 테스트마다 `tempfile` 경로를 쓴다.
- **실제 Docker 컨테이너·볼륨 생성, 시드 삭제, `benchmark.py` 실행은 하지 않았다.** 기동 확인(2.7절)도 항상 실패하는 가짜 `docker`를 `PATH` 앞에 두고 임시 `HOME`에서만 실행했다.
- 프로세스 시험(I-011~013, I-016)은 실제 OS 프로세스·세션·`killpg`·`ps -E`를 사용했다. 각 실행 뒤 `MINI_REDIS_LIVE_JOB=` 표지를 가진 프로세스와 테스트 서버 잔존 0개를 확인했다.

## 2. RED→GREEN 기록

명령은 모두 저장소 루트에서 `python3 -B -m unittest tests.test_live_benchmark.<클래스>`. 동작 묶음(클래스) 단위로 테스트를 먼저 쓰고 실패를 확인한 뒤 구현했다.

| 순서 | 묶음(TC) | RED 결과와 원인 | GREEN |
| --- | --- | --- | --- |
| 1 | `SeedInspectionTests` (U-001·002) | 3개 실행, errors 12 — `inspect_seed`가 `NotImplementedError` 골격 | 3/3 OK |
| 2 | `JudgeTests` (U-003~005) | 4개, errors 31 — `judge_run` 미구현(AttributeError) | 4/4 OK |
| 3 | `HttpContractTests` (I-006~008) | 6개, errors 6 — 서버 구성 요소 없음 | 첫 실행 5/6: 413 시험이 응답 첫 조각만 읽던 **테스트 결함**(헤더만 수신). EOF까지 읽도록 고친 뒤 6/6 OK |
| 4 | `RecordAndRecoveryTests` (I-010~013) | 10개, failures 6·errors 15 — `run_recover`·`marker_processes` 없음, 기동 시 미해제 작업 차단 없음. 단 I-010의 공유 기록 저장 실패 하위 사례는 3단계에서 구현한 의도 기록 때문에 RED가 아니었다 | 10/10 OK |
| 5 | `SetupAndSeedTests` (I-001~005, I-009, I-010 순서) | 10개, failures 17·errors 1 — 작업 실행부 미구현으로 작업이 끝나지 않음 | 10/10 OK |
| 6 | `RunTests` (I-011·012 중단 지점, I-014~016) | 11개, failures 12·errors 5 — 측정 작업 미구현, `INTERNAL_ERROR`로 실패 종결(성공 위장 없음) | 1차 9/11(실패 4건 = 중단 지점 하위 3 + I-015 1): 경로 별칭(`/var`↔`/private/var`) 비교와 공유 기록 없이 전용 자원을 미리 만든 **테스트 결함** 2건(서버는 계약대로 `SHARED_RECORD_MISSING`으로 거부). 2차 10/11: **제품 결함** — 재시작 뒤 `last_run_id`를 같은 초의 무작위 ID 사전순으로 골라 오답. `created_at` 기준으로 고친 뒤 11/11 OK |

중간 실패 실행의 로그 파일은 같은 이름의 GREEN 로그로 덮어썼다. 위 표의 중간 결과는 당시 터미널 출력에서 옮겼다. 1차 실패 때 남은 테스트 서버 프로세스 7개(임시 디렉터리·가짜 Docker 사용)를 종료했고, 이후 테스트 서버는 `addCleanup`으로 항상 회수하도록 고쳤다.

**수정 전 코드 전체 실행(현재 코드 아님, 6절 참조):** `python3 -B -m unittest discover -s tests -p 'test_live_benchmark.py' -v` → `Ran 44 tests in 60.944s OK`, `... ok` 44줄(`08-final-full.log`). 대상 해시: `examples/live_benchmark.py` `f7d9d583…f134`, `tests/test_live_benchmark.py` `80bd0a4f…d76f`(전체 값은 `new-hashes.txt`). 이 실행 뒤 제품·테스트 코드를 바꾸지 않았다. `py_compile` 두 파일 통과.

### 2.7. 실제 진입점 기동 확인 (가짜 `docker`, 임시 `HOME`)

`python3 -B .agent/verification/mini-redis-i07-server/smoke_entrypoint.py` 결과(`07-smoke.json`):

| 확인 | 실제 결과 |
| --- | --- |
| 기동 배너·리스닝 | `http://127.0.0.1:18765/`, `lsof` LISTEN `127.0.0.1:18765`만 |
| 같은 범위 두 번째 서버 / 실행 중 `--recover` | 종료 코드 2 / 2 |
| `GET /` | 200, `frame-ancestors 'none'`, `no-store`, 토큰 포함 |
| `GET /api/setup` | 200, `recovery_required` + `SHARED_RECORD_UNVERIFIED`(Docker 확인 불가로 공유 기록 미초기화) |
| `localhost` Host / 토큰 없는 POST / 유효 POST | 403 / 403 / 409 `RECOVERY_REQUIRED` |
| SIGTERM | 종료 코드 0 |
| 종료 뒤 `--recover` | 종료 코드 0, 공유 기록 없음 안내 |
| 가짜 `docker`에 전달된 호출 | `context show`, `container inspect mini-redis-live-mongo` 등 읽기 전용만 |

## 3. TC별 결과

`tests/test_live_benchmark.py`의 클래스·함수. **통과**는 위 최종 실행의 통과이며 이중물 위의 결과다. 실제 OS/Docker 동작 증거가 아니다.

| TC | 테스트 | 상태 | 확인한 범위 · 남은 부분 |
| --- | --- | --- | --- |
| U-001 | `SeedInspectionTests.test_u_001_*` (2) | 통과 | 읽기 호출만, 키 318개를 표본식 순서대로, 한 값 변조 시 `mismatch` |
| U-002 | `test_u_002_classification` (하위 10) | 통과 | 없음/건수/`demo`/양 끝/표본 → seed_required 계열, 조회 실패·캐시·크기 분류 |
| U-003 | `JudgeTests.test_u_003_*` (2) | 통과 | `mongo_after` 오류는 성공 유지 + 표시 |
| U-004 | `test_u_004_each_invalid_field_is_result_invalid` (하위 21) | 통과 | 부분 문자열 반례 포함 `--output` 인자 단위 |
| U-005 | `test_u_005_failures_and_timeouts` (하위 8) | 통과 | 파일 없음·손상은 `partial` 없음 |
| I-001 | `SetupAndSeedTests.test_i_001_*` | 통과(이중물) | 단계 구분·이름 있는 두 볼륨만·새 볼륨 1회 시드·재준비 무변경. 실제 Docker는 E-001 미실행 |
| I-002 | `test_i_002_*` (2, 하위 5) | 통과(이중물) | 표지 없음·설정/익명 마운트 불일치·포트 점유·볼륨 생성 경쟁. 실제 Docker 문구 미확인 |
| I-003 | `test_i_003_*` (3) + I-001 | 통과 | (a)(b), 시드 직전 재검사 실패, (c) 실제 서버 프로세스 SIGKILL → 복구 전 409 → `--recover` → `not_ready` → 재준비 `seed_required` |
| I-004 | `test_i_004_*` | 통과(이중물) | 확인값 우선 400, `ready`/`not_ready`의 409, 고정 명령 재생성 |
| I-005 | `test_i_005_*` (하위 5) | 부분 통과 | 데몬 불가·pull 실패·ping 초과·시드 실패/시간 초과. **Docker CLI 부재(`FileNotFoundError`) 경로는 자동 시험하지 않음** |
| I-006 | `HttpContractTests.test_i_006_*` (2) + `RunTests` 조회 | 통과 | 필드·헤더·404 |
| I-007 | `test_i_007_*` (2) + 2.7절 | 부분 통과 | Host/Origin/토큰/이전 토큰/OPTIONS 403, 루프백만. **실제 브라우저의 교차 출처 form·fetch 시험 미실행** |
| I-008 | `test_i_008_*` (2) + I-011 | 부분 통과 | 오류 종류·순서, 본문 미수신 413, 복구 차단 중 형식 오류 우선. **작업 진행 중(BUSY) 상태의 형식 오류 반복은 미실행** |
| I-009 | `test_i_009_*` | 부분 통과 | 준비 작업을 배리어로 붙잡고 세 POST 모두 `BUSY`·Docker 호출 0. **시드·측정 작업을 붙잡은 변형은 미실행** |
| I-010 | `RecordAndRecoveryTests.test_i_010_*` (3) + `test_i_010_intent_records_precede_any_docker_call` | 부분 통과 | 세 종류 × 공유/상세 최초 저장 실패 500·외부 작업 0, 공유만 남으면 재시작 뒤 차단, 초기화 조건. **성공 수락의 기록→Docker 순서 관찰은 준비 작업만** |
| I-011 | `test_i_011_*` (2) + `RunTests.test_i_011_*` (3, 하위 3) + `SetupAndSeedTests.test_i_011_step_record_failure_*` (하위 3) | 부분 통과 | 측정 작업의 자식 생성 전/생성 후 PID 기록 전/기록 후 실제 SIGKILL, 반복 재시작 차단, PID 기록 실패 즉시 회수·차단, 공유 기록 손상, 중단 표시 저장 실패, 단계 갱신 기록 실패(측정 `restarting`·준비 `preparing_volumes`/`starting_container`·시드 `seeding`) 뒤 Docker 변경·자식 생성 0건(6절). **시드 작업의 중단 지점, 작업 종료 시 공유 해제 저장 실패 주입은 미실행** |
| I-012 | `test_i_012_*` (2) + 중단 지점 시험 + I-013 상세 부재 시험 | 통과 | 실제 별도 서버 프로세스 간 잠금, A 중단 뒤 B 차단, A 상세 디렉터리 이동·해제 저장 실패 시 양쪽 차단. 디렉터리만/원자료만 남은 상세 부재·끊어진 링크는 6절 |
| I-013 | `test_i_013_*` (4, 하위 7+4) | 통과 | 살아 있는 표지 그룹·무관 그룹(PID 재사용 모형)·PID 없는 표지 프로세스·조사 실패·상세 위치 없음·상세/공유 증거 저장 실패 모두 차단·무신호. 증거 저장 뒤에만 `not_ready`. 상세 파일 부재(A·B)·끊어진 링크(C)·검증 불가는 생성·교체 0건으로 차단(6절) |
| I-014 | `RunTests.test_i_014_*` (2, 하위 4) | 통과(이중물) | 시드 읽기 → 재시작 1회 → 메타데이터만 → 측정기, 실패 4종 측정기 미시작. 실제 캐시 영향은 E-002 |
| I-015 | `test_i_015_*` (2) | 통과 | ID 형식·충돌 시 기존 파일 불변·`--output` 일치·재시작 뒤 조회, 응답에 절대 경로 없음 |
| I-016 | `test_i_016_*` (5) + I-005 시드 시간 초과 | 부분 통과 | 측정기: 리더 SIGINT로 끝남(partial 보존)/무시 시 그룹 SIGKILL, 정상 종료 뒤 잔존 자식 정리, 결과 전 오류, 생성 실패 무신호, 회수 미확정 차단(측정기·시드), 정상 종료 `SERVER_STOPPED`. **시드 프로세스 생성 실패·시드 중 정상 종료는 미실행.** 실제 `benchmark.py`의 잡히지 않는 SIGINT 구간은 미실행 |
| I-017 | — | 미실행 | 웹 화면은 다음 체크포인트 |
| E-001~003 | — | 미실행 | 실제 Docker·브라우저 시연 범위 |
| R-001~003 | — | 미실행 | 독립 코드·증거 검토 대상. 보호 파일 해시 비교만 아래 4절에 기록 |

## 4. 보호 파일 확인

`examples/benchmark.py`, `seed_mongo.py`, `origin_api.py`, `client.py`, `mini_redis/http_api.py`, `mini_redis/store.py`의 SHA-256이 작업 시작 전(`baseline-hashes.txt`)과 최종 실행 뒤(`final-hashes.txt`)에 동일하다. 이 파일들이 바뀌지 않았으므로 기존 테스트 스위트는 다시 실행하지 않았다.

## 5. 남은 위험

- 이중물이 실제 Docker CLI 출력·오류 문구·`StartedAt`과 다를 수 있다. 실제 `benchmark.py`·`seed_mongo.py`를 이 서버로 실행한 적이 없다.
- 시간 제한 값은 설계의 잠정값이며 실제 소요 시간을 관찰하지 않았다.
- [구현 기록의 알려진 한계](implementation.md#알려진-한계)(`ps -E` 가시성, PGID 재조회 구간, 서버 SIGKILL 뒤 Docker CLI 잔존) 참조.

## 6. 독립 코드 검증 결함 수정 (2026-11-19)

독립 코드 검증에서 재현된 두 결함만 고쳤다. 상세 기록 부재(A) 해제 예외는 별도 설계 결정 전까지 두지 않는다(기본 차단).

| 결함 | 새·변경 테스트 | RED(수정 전 코드) | GREEN |
| --- | --- | --- | --- |
| 1. `--recover`가 없는·끊어진 상세 기록을 새로 만들고 공유 기록을 `released`로 바꿈 | `RecordAndRecoveryTests.test_i_013_missing_or_unverifiable_detail_record_is_never_fabricated` (하위 A 디렉터리만, B 원자료·로그만, C 끊어진 링크, JSON 객체 아님) | A·B·C 모두 `exit 0`·`released`, JSON 배열은 `AttributeError` | 4/4 하위 통과 |
| 2. 단계 갱신 기록 실패 뒤에도 작업 계속 | `RunTests.test_i_011_step_record_failure_stops_before_restart_or_benchmark`, `SetupAndSeedTests.test_i_011_step_record_failure_stops_setup_and_seed_before_changes` (하위 `preparing_volumes`, `starting_container`, `seeding`) | 측정은 `succeeded`, 준비는 이후 `create_volume`·`run_container` 진행 | 통과 |

- RED 명령: 위 세 테스트를 지정한 `python3 -B -m unittest …` → `Ran 3, failures 6, errors 2`(`09-fix-red.log`). 시드 하위 사례 1건은 하위 사례 사이 시드 표지 파일 공유라는 테스트 위생 문제였다. 하위 사례별 경로로 고쳤다.
- 같은 수정 중 발견: 상세 기록이 JSON 객체가 아니면 서버 기동의 중단 표시(`mark_interrupted`)가 `AttributeError`로 기동 자체를 실패시켰다. 객체·일반 파일일 때만 표시하도록 고쳤다.
- 전체 회귀 1차 45/47: (가) I-012 고정 자료가 `seed` 공유 항목에 `run` 상세 기록을 연결해 새 작업 ID·종류 대조에 걸렸다(고정 자료 수정). (나) I-003 중단 시험이 간헐 실패했다. 서버 프로세스의 단일 작업 스레드가 Docker 이중물 상태 파일을 537바이트로 쓴 직후 SIGKILL되면 파일이 0바이트로 남는 현상을 계측으로 확인했다(동시 쓰기 없음, 쓰기 직후 크기 확인). 이중물 저장을 제품과 같은 내구 쓰기로 바꾼 뒤 해당 시험 8/8 반복 통과. 제품 기록은 원래 fsync·rename·부모 fsync를 쓴다.
- **현재 코드 전체 실행:** `python3 -B -m unittest discover -s tests -p 'test_live_benchmark.py' -v` → `Ran 47 tests in 63.371s OK`, `... ok` 47줄(`10-fix-final-full.log`). 대상 해시 `examples/live_benchmark.py` `150847e3…2892`, `tests/test_live_benchmark.py` `31255f85…f841`(`fix-hashes.txt`). 보호 파일 해시 불변. 실행 뒤 잔존 표지 프로세스·테스트 서버 0개.
- **실제 CLI 재현(`11-repro-missing-detail.json`, 스크립트 `repro_missing_detail.py`):** 임시 `HOME`·가짜 `docker`에서 `python3 -B -m examples.live_benchmark --recover`. A·B·C 모두 종료 코드 1, 공유 기록 `open`·바이트 불변, 실행 디렉터리 목록·내용 불변(B의 `results.json`·`benchmark.stdout.log`만 유지, C의 링크 대상 그대로), 이후 다른 checkout 서버 기동 상태 `recovery_required`, 기동 뒤에도 디렉터리 불변.

**미검증:** 실제 Docker 동작, 실제 `seed_mongo.py`의 컬렉션 `drop` 시점과 기록 실패의 상대 순서(시드 자식 생성 전 차단만 이중물로 확인), Linux `/proc/*/environ` 경로(macOS `ps -E`만 실행), 실제 디스크 오류에 의한 쓰기 실패(주입한 `OSError`만).
