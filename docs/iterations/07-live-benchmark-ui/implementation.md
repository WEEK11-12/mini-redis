# 7단계 구현 기록 — 로컬 준비·실행 서버 연결 (체크포인트 3)

- **상태:** 서버 연결 구현과 테스트 이중물 기반 자동 검증 완료. **실제 Docker·MongoDB·`benchmark.py` 실행, 브라우저 화면, 독립 검토는 아직 없다.** 진행 체크리스트 3번은 실제 작동 확인 전이므로 완료로 표시하지 않았다.
- **근거:** [D-0008](../../decisions/0008-live-benchmark-contract.md), [실행·화면 계약](execution-screen-contract.md), [설계](design.md), [TC](test-cases.md). 실행 결과는 [검증 기록 (verification.md)](verification.md).
- **변경하지 않은 것:** `mini_redis/`, `examples/benchmark.py`, `examples/seed_mongo.py`, `examples/origin_api.py`, `examples/client.py`. 구현 전후 SHA-256 동일(검증 기록 3절).

## 변경 경로와 역할

| 경로 | 역할 |
| --- | --- |
| `examples/live_benchmark.py` (신규) | 로컬 실행 서버 전체: 요청 보호·HTTP 계약, 작업 슬롯, 공유 잠금·공유/상세 내구 기록, Docker 전용 자원 준비, 읽기 전용 시드 검사, 측정 전 재시작·확인, 시드/측정기 자식 실행과 프로세스 그룹 회수, 결과 판정, `--recover` 복구 해제 도구 |
| `tests/test_live_benchmark.py` (신규) | TC-07-U-001~005, I-001~016의 자동화(44개 테스트). Docker·MongoDB는 이중물, 시드·측정기는 임시 스크립트 프로세스 |
| `.gitignore` | checkout별 원자료 위치 `/var/` 제외 추가 |

## 실행 방법 (실제로 확인한 명령만)

```sh
python3 -B -m examples.live_benchmark --port 8765   # 127.0.0.1:8765, Ctrl-C/SIGTERM으로 정상 종료
python3 -B -m examples.live_benchmark --recover     # 서버를 멈춘 뒤 미확정 작업의 종료 증거 확인·기록
```

위 두 명령은 **가짜 `docker`(항상 실패)와 임시 `HOME`** 에서만 실행해 기동·보호·잠금·정상 종료를 확인했다(검증 기록 2.7절). 실제 시연은 `examples/requirements-mongo.txt`가 설치된 Python으로 띄워야 한다. 측정기·시드는 서버의 `sys.executable`로 실행된다.

## 핵심 흐름

1. **기동:** 공유 디렉터리에 배타 `flock`(실패 시 종료 코드 2) → 공유 복구 기록 읽기. 기록이 없으면 `docker container/volume inspect`로 전용 자원 3개 부재를 읽기 전용 확인한 경우에만 초기화하고, 자원이 있거나 확인 불가면 `recovery_required`. 미해제 작업이 있으면 상세 기록을 `SERVER_INTERRUPTED`로 종결(최선 노력, 링크이거나 JSON 객체가 아니면 쓰지 않음)하되 차단은 유지한다. 준비 상태는 저장하지 않아 항상 `not_ready` 또는 `recovery_required`에서 시작한다.
2. **요청 수락:** 보호(Host 정확 일치·Origin 같은 출처·POST 토큰) → 경로·메서드 → 본문(`application/json`, 1KiB 초과는 본문을 읽지 않고 413) → 확인값 → 복구 차단 → 슬롯·상태 → **공유 기록 → 상세 기록** 내구 저장 → `202`. 저장 실패면 `500 RECORD_UNAVAILABLE`, 외부 작업·자식 없음.
3. **준비 작업:** `docker info` → 이미지(없으면 pull) → 볼륨(없으면 무작위 생성 표지로 만들고 재조회해 표지가 일치할 때만 "새 데이터 볼륨") → 컨테이너(없으면 고정 인자로 `docker run`, 있으면 표지·설정·마운트 검사 후 필요 시 `start`) → ping 대기 → 읽기 전용 시드 검사. 컬렉션 없음 **그리고** 이번 작업이 데이터 볼륨을 새로 만들었을 때만 표지·마운트 재검사 후 시드.
4. **시드 작업(`/api/setup/seed`):** `seed_required`에서만 수락. 자원 재검사 → ping → 시드 직전 재검사 → `seed_mongo.py` → 재검사.
5. **측정 작업:** 자원 검사 → 시드 검사(재시작 전, 문서 읽기) → `docker restart` 1회 → `StartedAt` 변화·ping·캐시 한도·`collStats.count`만 확인(문서 읽지 않음) → `benchmark.py --output <실행 디렉터리>/results.json --mongo-uri mongodb://127.0.0.1:27018` → 판정.
6. **기록 갱신 실패:** 수락 이후 상세 기록의 단계·결과 갱신이 실패하면 그 자리에서 작업을 멈추고 `failed: RECORD_UNAVAILABLE`로 끝낸다. 이후 Docker 변경·자식 생성은 하지 않으며 공유 기록은 open으로 남아 `recovery_required`가 된다. 종결 기록만 실패를 숨기지 않는 최선 노력 쓰기다.
7. **자식 회수(시드·측정기 공통):** 새 세션으로 시작 → 즉시 PID/PGID를 상세·공유 기록에 저장(실패 시 메모리의 신원으로 바로 회수하고 미확정 유지) → 제한 시간·정상 종료 요청 시 **리더 PID에만 SIGINT** → 유예 뒤 `killpg(SIGKILL)` → 정상 종료 뒤에도 `killpg(pgid, 0)`으로 그룹 잔존 확인, 남으면 그룹 SIGKILL 후 `ESRCH` 대기. 그래도 남으면 `leftover=true`.
8. **종결:** 상세 기록에 종결·회수 결과 → 회수 확인과 모든 기록 성공일 때만 공유 기록을 `released`. 아니면 `recovery_required`.
9. **복구 해제(`--recover`):** 서버가 잠금을 쥐고 있으면 거부. 참조 상세 기록이 심볼릭 링크를 포함해 존재하지 않거나(`os.path.lexists`), 링크이거나, 읽을 수 없거나, 공유 기록의 작업 ID·종류와 맞지 않으면 아무 파일도 만들거나 바꾸지 않고 차단을 유지한다(상세 기록 부재의 조건부 해제는 별도 설계 결정 전까지 보류). 그 밖에 미해제 작업마다 기록된 모든 PGID가 `ESRCH`이고, 같은 사용자 프로세스 환경 변수 중 작업 표지(`MINI_REDIS_LIVE_JOB=<marker>`)를 가진 것이 없으며, 상세 기록 위치가 접근 가능할 때만 상세 → 공유 순서로 증거를 내구 저장하고 `released`. 어떤 프로세스에도 신호를 보내지 않는다.

## 설계에서 위임된 구현 선택

| 항목 | 선택 |
| --- | --- |
| 모듈·HTTP 서버 | 단일 모듈, 표준 라이브러리 `ThreadingHTTPServer`, 기본 포트 8765(`--port`만 변경 가능) |
| 공유 잠금·복구 기록 위치 | `~/.mini-redis-live-benchmark/<sha256([uid, docker context show 결과, DOCKER_HOST, 컨테이너·볼륨 이름])[:16]>/{lock, recovery.json}`. `docker context show` 실패 시 context를 `unavailable`로 둔다(이 경우 초기화 확인도 불가해 차단 상태) |
| checkout별 기록 | `var/live-benchmark/runs/<run_id>/runner.json`(+ `results.json`, `results.servers.log`, `benchmark.stdout.log`, `benchmark.stderr.log`), 준비·시드는 `var/live-benchmark/jobs/<job_id>/job.json`(+ `seed.stdout.log`, `seed.stderr.log`) |
| 작업 식별 표지 | 작업마다 `secrets.token_hex(16)`을 자식 환경 변수 `MINI_REDIS_LIVE_JOB`으로 전달. 측정기의 자식 서버와 Docker CLI 호출도 상속한다. 복구 판정은 Linux `/proc/*/environ`, macOS `ps -E -ww -A` |
| 복구 해제 경로 | 화면 밖 CLI `--recover`만. 서버 재시작·화면 확인은 증거가 아니다 |
| Docker 출력 해석 | `inspect` 실패 중 stderr에 `no such`가 있을 때만 "없음", 그 밖은 오류. `docker run` 실패 stderr의 `port is already allocated`/`address already in use`는 `PORT_CONFLICT` |
| 측정 키 재사용 | `examples.benchmark`의 `KEY_SEED`·`WARMUP`·`ROUNDS`·`CONDITIONS`, `seed_mongo.value_for`/`item_id`, `origin_api.DEMO_*`를 가져와 같은 표본식으로 315개 + `demo`·`item-0`·`item-999999`를 한 번의 `$in` 조회로 검사 |
| `GET /` | 토큰을 `<meta name="live-bench-token">`에 넣은 **임시 안내 페이지**. 버튼·그래프 화면은 다음 체크포인트(4번) 범위 |

## 계약에 없던 코드·필드 (추가 근거)

- 실행 오류 코드: 시간 초과 실행의 `error.code=TIMED_OUT`, 서버 정상 종료 시 `SERVER_STOPPED`, 예상하지 못한 예외 `INTERNAL_ERROR`(실패로 종결, 성공 위장 없음), PID 기록 실패로 중단한 실행 `RECORD_UNAVAILABLE`.
- 준비 상태 오류: 측정 전이 아닌 시드 검사로 `seed_required`가 되면 `SEED_REQUIRED`(+`reason: missing|mismatch`, `detail`). 차단 사유 코드 `RECOVERY_REQUIRED`, `RECORD_UNAVAILABLE`, `SHARED_RECORD_MISSING`(기록 없음+전용 자원 있음), `SHARED_RECORD_UNVERIFIED`(기록 없음+Docker 확인 불가), `SHARED_RECORD_UNREADABLE`.
- 준비 중 Docker 조회·명령 자체가 실패하면 `DOCKER_UNAVAILABLE`. 측정/시드 전 컨테이너가 꺼져 있으면 `MONGO_NOT_READY`.
- 종료 코드 0·유효 결과지만 회수 미확정이면 새 코드를 만들지 않고 `BENCHMARK_FAILED`(메시지로 회수 미확정 명시) + `recovery_required`.
- 측정기가 정상 종료한 뒤 그룹 잔존을 SIGKILL로 정리하고 `ESRCH`를 확인하면 회수 확인으로 보고 성공 판정을 허용한다(설계 5절 4·6항 해석).
- `active_job`에 `job_id` 추가. 실행 조회에 `steps`, `precheck`, `restart`, `reap`, `partial` 추가. `resources.retained_on_exit=true`.
- 최초 의도 기록 중 **공유 기록** 저장이 실패해도 디스크 반영 여부를 알 수 없으므로 메모리 차단(`recovery_required`)한다. 서버를 재시작하면 디스크의 공유 기록으로 다시 판정한다.
- `last_run_id`는 서버 재시작 뒤 `runner.json`의 `created_at` 최댓값으로 복원한다(같은 초의 실행 ID는 사전순과 생성순이 다를 수 있어 테스트에서 발견해 수정).

## 알려진 한계

- Docker CLI 출력 문구, `docker restart` 뒤 `StartedAt` 변화, 익명 볼륨 부재, `collStats`의 캐시 영향, 실제 측정기 실행 시간은 실행하지 않았다(E-001~003).
- macOS `ps -E`는 SIP 보호 바이너리의 환경 변수를 보여 주지 않는다. 작업 자식은 python·docker이므로 해당하지 않는다고 가정한다(코드에 `shortcut:` 주석). 다른 사용자 프로세스는 신뢰 경계 밖이다.
- 회수 직후 PGID를 다시 조회하는 짧은 구간에 무관한 새 세션 리더가 같은 번호를 얻으면 잔존으로 오판(차단 방향)할 수 있다.
- 준비 중 Docker CLI 호출은 새 세션이 아니다. 서버가 SIGKILL되면 진행 중이던 CLI가 자체 제한 시간까지 남을 수 있으며, 표지 환경 변수 때문에 그동안 `--recover`는 해제하지 않는다. 정상 종료 요청 시 진행 중인 Docker 단계(최대 pull 600초)는 끝난 뒤 멈춘다.
- 상세 기록이 사라진 작업은 `--recover`로 해제할 수 없어 수동 조사·별도 결정이 필요하다(의도한 기본 차단).
- 정리 버튼/API는 없다. 수동 정리 명령은 실제 자원 확인 뒤 문서화하기로 한 설계에 따라 아직 작성하지 않았다.

## 체크포인트 4 — 웹 화면 (2026-11-19)

- **상태:** 화면 구현과 자동 검증(이중물·격리 서버·headless 브라우저) 완료. 실제 Docker·`benchmark.py` 결과를 표시해 본 적은 없어 진행 체크리스트 4번은 체크하지 않았다.

| 경로 | 역할 |
| --- | --- |
| `examples/live_benchmark_ui.html` (신규) | 정적 화면 틀: 준비 상태, 작업 버튼 3개(준비·비교 실행·시드 재생성), 시드 삭제 영향 확인, 최근 실행, Docker 자원 유지 안내, 결과 해석 한계 |
| `examples/live_benchmark_ui.js` (신규) | 화면 판단 함수(`controls`, `banner`, `runView`, `guideFor`, `stepLabel`, `seedRequest`)와 브라우저 연결. Node에서 같은 파일을 `require`해 시험 |
| `examples/live_benchmark.py` | 기존 임시 페이지 대신 위 두 파일을 시작 시 읽어 `GET /`에 인라인으로 제공(`render_page`, `page_csp`). 새 경로·API 없음 |
| `tests/live_benchmark_ui.test.js` (신규) | 화면 판단 Node 테스트 12개(검증 지적 반영 3개 포함) |
| `tests/test_live_benchmark.py` | `ScreenPageTests` 3개 추가, I-006 CSP 기대값을 "포함"으로 변경 |

**구현 선택**

- 정적 자원은 별도 경로 없이 HTML 하나에 인라인. 응답마다 새 nonce를 만들고 CSP를 `default-src 'none'; script-src 'nonce-…'; style-src 'nonce-…'; connect-src 'self'; img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`으로 보낸다(계약의 `frame-ancestors 'none'`을 포함하는 확장). 외부 CDN·네트워크 자원은 없다.
- 토큰은 서버가 `<meta name="live-bench-token">`에 HTML 이스케이프해 넣고, 스크립트는 그 값을 POST의 `X-Live-Bench-Token`으로만 쓴다. 서버 응답 문자열은 모두 `textContent`로 넣고 `innerHTML` 계열·`eval`을 쓰지 않는다. 막대 너비는 CSSOM(`element.style.width`)으로 설정한다.
- 상태 조회는 1초마다 `GET /api/setup`, 그다음 `active_job.run_id` 또는 `last_run_id`로 `GET /api/runs/{id}`. 새로고침 뒤에도 같은 실행 ID를 다시 찾는다(브라우저 저장소 미사용).
- 버튼 활성: 진행 중 작업(`active_job`)이 있거나 상태가 `preparing`·`recovery_required`·알 수 없는 값이면 모두 비활성. 그 외 준비는 `not_ready`·`ready`·`seed_required`·`failed`, 비교 실행은 `ready`, 시드 재생성은 `seed_required`이면서 삭제 영향 확인 체크박스를 선택한 경우만. 요청 뒤 체크박스는 해제한다.
- **복구 우선:** `recovery_required`면 실행 기록이 `running`/`preparing`으로 남아 있어도 배너는 복구 필요와 `--recover` 안내를 보이고 버튼을 막는다. 실행 기록이 `running`/`preparing`인데 서버의 `active_job.run_id`와 다르거나 복구 차단 중이면 진행 중으로 표시하지 않고 "종결되지 않은 기록, 결과로 보지 않음"으로 표시한다.
- **결과 표시:** `succeeded`이고 `result.conditions`가 정확히 세 조건이며 각 중앙값·P90이 유한한 비음수, 성공 100·실패 0이고 `method`·`environment`가 객체일 때만 비교 그래프(중앙값·P90 막대)와 표를 그린다. 아니면 "결과 형식 확인 불가"로 수치를 숨긴다. `failed`/`timed_out`은 서버가 준 `partial`의 정수 성공·실패 수만 "완결 결과 아님" 표로 보이고 그래프는 그리지 않는다.
- 진행 중에는 단계 이름만 보이고 퍼센트·조건별 수치·경과 시간은 표시하지 않는다.
- 오류 코드별 안내는 계약·구현의 코드 전부에 고정 문구로 둔다. 알 수 없는 코드는 일반 문구를 쓴다. 화면 전용으로 요청 실패를 `NETWORK`, 오류 본문이 없는 응답을 `HTTP_<상태>`로 오류 상자에만 표시한다(서버 상태·API 이름이 아님).
- 정리·삭제 버튼은 없다. 자원 안내는 자동 중지·삭제되지 않는다는 사실과 수동 정리 원칙만 적고 구체 명령은 넣지 않았다(아래 결정 필요 항목).

**결정이 필요한 항목 (임의로 정하지 않음)**

1. 계약·E-003은 화면에 "전용 자원의 안전한 수동 정리 방법"을 요구하지만, 설계 4.4는 실제 정리 명령을 실제 자원 확인 뒤 문서화하도록 했다. 현재 화면은 원칙만 있고 명령이 없다.
2. 복구 필요 상태에서 서버 메시지와 화면 안내가 모두 `--recover`를 말해 문구가 중복된다(기능 영향 없음). 단 `SHARED_RECORD_UNREADABLE`은 서버 메시지 자체에 `--recover` 안내가 붙지만 `--recover`로 해소되지 않는다. 서버 문구는 이번 범위 밖이라 바꾸지 않았다.

**독립 검증 지적 반영 (2026-11-19)** — `examples/live_benchmark_ui.js`만 변경(HTML·서버 불변)

- `banner()`(80줄~): 복구 필요 상태에서 차단 코드가 `SHARED_RECORD_MISSING`·`SHARED_RECORD_UNVERIFIED`·`SHARED_RECORD_UNREADABLE`이면 `--recover` 대신 기존 `guideFor(code)`를 보인다(`NOT_RECOVERABLE`, 24줄). `run_recover`는 공유 기록이 없거나 읽을 수 없으면 아무것도 해제하지 않으므로 세 코드 모두 해당한다. 그 밖의 복구 필요 코드는 그대로 `--recover` 안내. 새 상태·코드 없음.
- `createPoller()`(97줄~): 정기 폴링은 진행 중인 조회가 있으면 건너뛰고(`skipped`), POST 직후 갱신은 강제로 새 조회를 보내며(`force`), 요청 순번이 마지막 반영분보다 오래된 응답은 버린다(`stale`). 브라우저 연결부는 조회를 `fetchState()`(365줄~)로 분리해 순수 결과만 돌려주고 반영은 poller가 한다(379~395줄).
