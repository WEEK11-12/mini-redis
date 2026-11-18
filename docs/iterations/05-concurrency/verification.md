# 5단계 검증 기록 — 동시성·실패 경계와 최종 회귀

- 상태: 5단계 범위 검증 완료 — 계측 적용 동시성 25/25, 수정 후 HTTP 회귀 47/47, 보완 검증 10/10 통과; 범위·계측 한계는 아래 최종 검증 절 참조
- 근거: [TC 목록](test-cases.md), [요구사항](requirements.md), [설계](design.md)

## 구현 전 자체 확인 (당시 순차 서버 기준)

저장소 루트에서 Python 3.14로 `tests/test_concurrency_http.py`를 작성했다. `R-001`·`R-002`는 코드 검토 항목이며 실행 테스트 수에 포함하지 않는다. 제품 코드는 바꾸지 않았다.

| 대상 | 실제 명령·조건 | 실제 결과 | 판정·한계 |
| --- | --- | --- | --- |
| 구문·발견·TC 매핑 | `python3 -m py_compile tests/test_concurrency_http.py`; `unittest.TestLoader.discover('tests', pattern='test_concurrency_http.py')`의 ID와 TC 목록 비교 | 구문 통과, 통합 TC 25개와 `test_i_001`~`025` 25개가 일대일 대응 | 수집·구문 확인일 뿐 테스트 본문 전체 실행 아님 |
| 초점 RED·기존 계약 대조 | `PYTHONPATH=tests python3 -m unittest test_concurrency_http.ConcurrencyHTTPTests.test_i_001_slow_body_does_not_block_other_client test_concurrency_http.ConcurrencyHTTPTests.test_i_005_unordered_same_key_results_are_serializable test_concurrency_http.ConcurrencyHTTPTests.test_i_017_oversize_rejected_before_body_and_no_followup -q` | 3개 실행: I-001 `TimeoutError`(느린 PUT 동안 B 처리 불가), I-005 실패(저장소 호출 스레드가 서버 루프와 동일), I-017 통과(초과 선언 본문 읽기·저장소 미접근 및 기존 오류 계약) | **1 통과·1 실패·1 오류**. 앞 두 RED는 현재 순차 서버와 설계 목표의 차이이며 5단계 동작 통과 아님. I-017은 기존 입력 경계 회귀의 제한된 대조만 확인 |
| 계측 대조 | `PYTHONPATH=tests python3 -c 'import threading; from test_concurrency_http import ObservedStore,Clock; s=ObservedStore(Clock()); [s.set(str(i),str(i)) for i in range(8)]; s.hold("rehash",None); t=threading.Thread(target=s.set,args=("ninth","9")); t.start(); assert s.entered.wait(2); assert len(s._buckets)==8; s.unblock(); t.join(2); assert not t.is_alive() and (len(s._buckets),s._size)==(16,9) and not s.overlap; q=ObservedStore(Clock()); q.hold("get","a"); w=threading.Thread(target=q.get,args=("a",)); w.start(); assert q.entered.wait(2); q.exists("b"); q.unblock(); w.join(2); assert q.overlap; print("observer positive and concurrent counterexample: OK")'` | `observer positive and concurrent counterexample: OK` | 동일 스레드 내부 중첩은 겹침으로 판정하지 않고 다른 스레드 진입은 감지; 실제 서버의 5단계 명령 경계 검증 아님 |
| 문서·작업 트리 | `git diff --check` | 통과 | 새로운 미추적 테스트·TC 파일은 Git diff 통계에 포함되지 않으므로 상태 목록에서 별도 확인 |

독립 테스트 코드 검토는 **수정 요청**이었다. I-019의 GET 계수, 제출 순서·배출 전환 관찰, I-006의 정리/확장 경합, I-005의 실제 실행 순서와 응답 대조, 종료 교착 시 테스트 무기한 대기를 제한 수정했다. 제한 재검토에서 `server_close()`의 non-daemon 요청 스레드 대기 반례가 추가로 확인되어 I-023~025의 서버 수명 전체를 자식 프로세스에서 실행하고 부모가 30초 뒤 종료·회수하도록 보완했다. 앞 표의 I-001·I-005 RED와 계측 대조는 이 수정 전 실행이며 최종 코드 재실행 결과가 아니다. 수정 후에는 AST로 통합 함수 25개 발견, 서로 다른 PUT 인자 기록·종료 watchdog 반례를 확인했다. I-005/I-017 초점 실행은 수명 격리 수정 이전에 **1 예상 RED(I-005: 저장소가 서버 루프 스레드에서 실행)·1 통과(I-017)**였다. 수명 격리 수정 후 I-023 초점 실행은 자식 프로세스의 임시 `_test_crash_executor` 부재 실패를 부모에게 전달하는 예상 RED였고, `python3 -m py_compile tests/test_concurrency_http.py`와 `git diff --check`는 통과했다. 수정 범위의 독립 재검토에서 이전 네 지적의 해소와 I-023~025 수명 격리를 각각 제한 승인받았다. 마지막 검토는 실제 `server_close()` 정지 반례에서 부모의 30초 실패 전달·자식 종료와 회수까지 확인했다. 이 판정은 TC 코드의 해당 지적에 한정되며 제품 기능·전체 TC 승인과 다르다. 이 문장 갱신은 마지막 검토 대상 소스 스냅샷 이후의 문서 변경이다.

제출 순서·수용량·오류 주입·종료·실행 시계 관찰은 **임시 시험 접점**으로 표시했다(`_test_pending_commands`, `_test_draining`, `_test_accepted_requests`, `_test_request_deadline_seconds`, `_test_submission_gate`, `_test_fail_response_write`, `_test_fail_delivery`, `_test_crash_executor`, `_test_admission_gate`). 이 이름은 제품 API가 아니며 구현 시 실제 구조에 맞추어 테스트 계측을 조정한다. 기존 코드에는 해당 접점이나 목표 전담 실행 스레드가 없다. **전체 25개 실행과 2~4단계 회귀는 미실시**다. I-019의 제출 후 단절 요청 자리 유지, I-024의 배출 중 기존 해석 요청 제출, I-025의 배출 중 정리 목표·순서, 느린 응답·거부 경계는 구현 후 별도 보완/확인 대상이다. 문서화된 TC 한 행에 여러 조건이 있는 경우 함수 발견만으로 모든 세부 조건이 검증됐다고 판단하지 않는다.

## 제품 구현 후 자체 확인

위 절의 RED와 미실시 표시는 **구현 전 스냅샷**에 관한 기록이다. `mini_redis/http_api.py` 변경 뒤 저장소 루트의 Python 3.14에서 `python3 -m unittest discover -s tests -p 'test_concurrency_http.py' -q`를 한 차례 실행했다: 25개 중 실패 16개. 대부분 `_test_*` 임시 시험 접점 부재이고 I-016은 테스트 `parsed()`가 `Allow` 값까지 소문자로 변환한 것과 대문자 기대값의 불일치다. 전체 통과가 아니다. 이 전체 실행은 마지막 제품 편집 **전** 결과다.

마지막 제품 편집 뒤 `python3 -m unittest discover -s tests -p 'test_http_api.py' -q` 32개 통과, `python3 -m unittest discover -s tests -p 'test_expiration_http.py' -q` 15개 통과, `PYTHONPATH=tests python3 -m unittest test_concurrency_http.ConcurrencyHTTPTests.test_i_001_slow_body_does_not_block_other_client test_concurrency_http.ConcurrencyHTTPTests.test_i_002_all_public_operations_use_one_execution_thread test_concurrency_http.ConcurrencyHTTPTests.test_i_003_idle_sweep_and_get_never_overlap test_concurrency_http.ConcurrencyHTTPTests.test_i_005_unordered_same_key_results_are_serializable test_concurrency_http.ConcurrencyHTTPTests.test_i_012_sweep_failure_and_diagnostic_failure_are_isolated test_concurrency_http.ConcurrencyHTTPTests.test_i_017_oversize_rejected_before_body_and_no_followup test_concurrency_http.ConcurrencyHTTPTests.test_i_022_store_failure_is_500_and_next_request_survives -q` 7개 통과. `python3 -m py_compile mini_redis/http_api.py`와 `git diff --check` 통과. 저장소 2·4단계 단위 테스트는 마지막 편집 전 각각 24·15개 통과했으며 마지막 편집 이후 재실행하지 않았다. 별도 실소켓 자체 확인에서 미완료 요청 16개 점유 중 GET·HEAD 거부의 `503`, `no-store`, HEAD 본문 부재를 확인했다. 이 점검 역시 독립 인수 판정이 아니다.

남은 범위: 임시 시험 접점을 실제 경계에 맞추는 계측, 제출 직전 단절·전달 실패·전담 스레드 사망·종료 경합과 단계 마감의 독립 검증, 전체 25개와 변경 후 전체 회귀 재확인. 수용 전 단절은 TCP 반닫힘과 완전 단절을 원자적으로 구별할 수 없어 정확한 적용 여부 보장은 제한된다.

## 최초 독립 검토와 제한 수정 (최초 검토 소스 이후)

독립 검토는 에이전트 전용 검토 산출물에 수정 요청 3건을 기록했다. 원본 TC의 scratch 계측 복사본 12/12 통과와 독립 probe 11건 중 7통과·4실패(세 고유 결함 중 완료 통지 실패 두 재현)였으며 전체 공식 25개 승인과 구분한다. 제품·원본 테스트 파일은 검토 중 수정하지 않았다.

세 결함을 `mini_redis/http_api.py`에서 제한 수정했다. 이후 별도 scratch probe `i05-fixes-probe.py` 실행으로 완료 통지 첫 실패 시 해당 PUT 1회·500, 다른 PUT 200, GET으로 저장값 유지, 전담 스레드 지속과 자리 반환 및 제출 전 실제 RST 관찰 후 미적용을 확인했다(2개 초점 통과). 검토 scratch의 `probes.py cli_sigint` 실행으로 실제 CLI SIGINT 후 종료 코드 0을 확인했다. 실제 실행 절대 경로는 로컬 `.agent/context.md`에 남긴다. `PYTHONPATH=tests python3 -m unittest test_concurrency_http.ConcurrencyHTTPTests.test_i_001_slow_body_does_not_block_other_client test_concurrency_http.ConcurrencyHTTPTests.test_i_017_oversize_rejected_before_body_and_no_followup test_concurrency_http.ConcurrencyHTTPTests.test_i_022_store_failure_is_500_and_next_request_survives -q` 3/3 통과, `python3 -m py_compile mini_redis/http_api.py`와 `git diff --check` 통과. 이 재확인은 세 수정 경로·직접 영향 범위에 한정한다. 앞 절의 전체 HTTP 32개·만료 HTTP 15개·기타 5단계 초점 실행은 이번 수정 **이전** 증거이며 재실행하지 않았다. 이 자체 확인 시점에는 독립 제한 재검토 전이어서 세 결함 해소 판정을 보류했다.

제한 재검토에서 세 결함 해소와 직접 영향 경로를 **제한 승인**했다. 검토용 scratch probe의 최종 고유 사례는 8/8 통과(시도 9회: 최초 계측이 같은 키의 후속 정상 GET까지 실패시킨 fixture 오류 1회 후 해당 사례만 수정·재실행), watchdog 만료 0회였다. 최초 실패의 계측 오류는 제품 결함이나 최종 통과로 바꾸지 않고 보존했다. 완료 통지의 1회·연속 실패, 실제 CLI SIGINT, 제출 전 RST/마감, FIN 반닫힘, 제출 후 단절, 저장소 ConnectionAbortedError를 확인했다. 검토한 제품 `http_api.py`의 SHA-256은 `ba7699259d51795e6653d3aa858fe1105d1067c66d92ec9a7fc9f04d477b8965`이며 현재 제품 소스와 일치한다. 이 문단과 앞 상태 문구는 당시 검토 스냅샷 **이후 문서만 갱신**한 것이다. 이 제한 재검토 시점에는 공식 25개 전체 최종 실행, 16/17번째 접수 단절 조합, 과부하 응답 backpressure, 결합 실패·장시간 부하와 수정 후 HTTP/TTL 전체 재실행이 미확인이었다. 아래 최종 검증에서 그 공백을 보완했다.

## 최종 검증 — 5단계 범위 승인

### 대상과 계측 경계

Python 3.14.5에서 `http_api.py` SHA-256 `ba7699259d51795e6653d3aa858fe1105d1067c66d92ec9a7fc9f04d477b8965`인 수정본을 확인했다. 제품·원본 테스트 파일은 실행 전후 동일하며, 이전의 F1~F3 제한 승인 결과도 같은 제품 해시에 적용된다. 이번 작업은 테스트 계측과 실행·문서 정리에 한정했다.

`tests/test_concurrency_http.py`의 **25개 TC 본문을 scratch 복사본에서 실제 내부 경계에 연결**했다. `_commands`는 큐 mutex 아래 관찰하고 `_active`는 condition 아래 읽었다. 제출·전달·응답 오류는 해당 명령/응답만 감쌌으며, 접수와 종료의 양쪽 순서는 실제 조건 잠금·수용 경계에 동기화했다. 수명 TC는 기존의 자식 프로세스 격리를 유지하고 그 자식에도 동일 계측을 적용했다. 테스트 skip·기대 상태/값 완화나 제품용 `_test_*` API 추가는 하지 않았다.

계측 복사본의 보정은 다음과 같다.

- I-016: 헤더 이름만 소문자화하고 `Allow` 값은 원문을 유지한다.
- I-019: 제출 전 **확인 가능한 완전 단절**은 실제 RST로 만든다. 단순 FIN은 유효한 반닫힘일 수 있어 미적용 oracle로 쓰지 않는다.
- I-024: 접수 중단 뒤 OS backlog 연결에는 애플리케이션 응답을 보장하지 않으므로 새 거부 연결의 관찰을 0.3초로 제한했다. 받은 응답은 기존 503 assertion으로 검사하며, 기존 수용 요청의 3초 클라이언트 제한을 이 관찰로 소진하지 않는다.
- I-025: 새 연결이 접수 루프의 gate에 도달한 뒤 수용·종료 전환 순서를 제어한다. 종료가 먼저 루프를 멈춰 시험 gate에 도달하지 못하는 계측 경합을 보정했다.

이 결과는 **계측 적용본의 25/25**다. 원본 테스트에는 임시 접점이 남아 있으므로 저장소의 보정 없는 `unittest discover` 명령 자체가 25개 모두 Green이라고 해석하지 않는다. 계측·로그는 로컬 검토 산출물이며 테스트 인프라의 저장소 반영은 이번 제품 검증과 별개다.

### 실행 결과와 명령

저장소 루트에서 `python3 -B "$REVIEW_ARTIFACTS/<script>"`로 아래 스크립트를 실행했다. `REVIEW_ARTIFACTS`는 로컬 보존본 `.agent/verification/mini-redis-i05-final` 또는 그 원본 검토 디렉터리다. 정적 검사 통과 보고는 제품 변경이 없어 재사용했고 반복하지 않았다.

| 범위 | 실제 명령의 script/인자 | 최종 고유 결과 | 근거·제한 |
| --- | --- | --- | --- |
| 동시성 I-001~025 | `full_concurrency.py`; `full_concurrency.py --case test_i_025_admission_shutdown_race_and_sweep_drain` | **25/25 통과** | 최초 전체 실행은 24통과·I-025 계측 실패(exit 1). gate 경합 보정 뒤 해당 1개만 재실행(exit 0). 최신 결과를 TC ID로 집계해 문서 카탈로그 25개와 일치 확인. |
| HTTP·만료 HTTP 회귀 | `regression.py` | **47/47 통과** | 원본 HTTP 32개·만료 HTTP 15개, 실패/오류/skip 0, exit 0. 이번 수정본에서 실행했으며 이전 자체 확인을 대신 인용한 결과가 아니다. |
| 수용량·느린 거부·결합 실패·TTL/확장 보완 | `gaps.py`; `gaps.py rejection_backpressure` | **7/7 통과** | 최초 6통과·backpressure 유도 미성공 1개. 해당 경계만 계측 보정/재실행하여 최종 통과. |
| 배출 중 해석 요청·정리 순서 | `../mini-redis-i05-review/probes.py drain_existing_parsing`; `../mini-redis-i05-review/probes.py drain_due_sweep` | **2/2 통과** | 기존 probe를 이번 제품 해시에서 실행, 각각 exit 0. |
| 60초 혼합 요청 반복 | `load.py` | **1/1 통과** | 8클라이언트, 60.453초, 1,134주기·HTTP 7,938건, 주기 정리 58회. 저장소 스레드 1개·호출 중첩 없음·최종 물리 수 0·자리 반환·종료 완료. 처리량 비교 시험이 아니다. |

새 실행의 최종 고유 사례는 **82/82 통과**다(동시성 25 + HTTP 47 + 보완 7 + 배출 2 + 반복 시험 1). 사례 실행 시도는 86회이며 계측 실패 4회(I-025의 gate 도달 경합 1회, 실제 송신 정체를 만들지 못한 backpressure fixture 3회)를 포함한다. 실패 원본 로그를 보존하고 해당 사례만 보정·재실행했다. 이를 제품 결함이나 처음부터 전 시도 통과로 바꾸지 않았다. 배출 probe를 잘못된 모듈에서 호출한 진입 전 명령 오류 2회는 사례 수와 별도로 보존했다. 최종 집계는 `summary.json`의 ID별 최신 결과에 근거한다.

변경 없는 `store.py` 및 저장소 테스트의 기존 24/24·만료 저장소 15/15는 재사용했다. 이 39개를 이번 새 실행 82개에 더하지 않았다. 시험 자식 watchdog 만료는 없었다. 검증 도중 한 차례 대화 턴이 중단됐으나, 재개 시 제품 해시와 보존 결과를 확인하고 남은 backpressure 경계와 문서 정리를 완료했다.

### 이전 미확인 조합의 보완 결과

- I-013/019: 제출 후 RST 요청의 자리를 유지한 상태에서 15자리 점유를 관찰했다. 16번째는 수용되고 17번째는 503으로 거부됐다. 해제 뒤 수용 PUT 16건이 각각 한 번 적용되고, 끊긴 요청도 1회 적용·거부 요청은 미적용이었다.
- I-013/015: 명령 큐가 비어도 응답 단계에 머문 요청 16개가 자리를 유지했다. 17번째 HEAD는 503·본문 0바이트, 해제 뒤 자리가 회복됐다.
- I-018: 거부 요청 행·헤더의 trickle은 유한 시간에 연결이 끝나고 다음 거부 처리가 진행됐다. 실제 TCP 송신 정체 시험에서는 수신을 중단한 연결의 OS 송신 큐를 시험 바이트로 포화시킨 뒤 **원본 `_reject`의 실제 `sendall`**이 0.501초에 타임아웃, 거부 경계가 종료되고 다음 연결에 503을 보냈다. 시험용 사전 송신 바이트는 HTTP 응답이 아니며, 이 연결에 유효한 503 본문이 전달됐다고 주장하지 않는다.
- I-020~022: 한 전담 스레드 아래에서 완료 통지·저장소 연산·응답 쓰기·입력 오류와 정리/진단 오류를 함께 주입했다. 실패는 각각 500/연결 종료/400으로 격리되고 정상 요청 200, 이미 확정한 세 값의 1회 적용·새 GET 보존, 실행 주체 지속과 자리 반환을 확인했다.
- I-006/007: 확장 중 같은 키 덮어쓰기·삭제·만료 GET/exists를 제출 순서대로 대기시켜 용량 16·물리 수 7과 새 값 보존을 확인했다. 갱신한 TTL의 옛 기한/새 기한 직전·정확한 기한에 GET·exists·DELETE를 나누어 확인하고 다른 키와 물리 수를 대조했다.
- I-024/025: 이번 제품 해시에서 배출 중 기존 해석 요청의 제출·완료, 배출 중 정리→대기 명령 순서와 배출 완료 뒤 정리 중지를 별도 2개 실제 소켓 probe로 확인했다. 이번 25개 실행에서 접수/종료 양쪽 확정 순서도 확인했다. 정상 CLI 종료는 같은 제품 해시의 F2 제한 재검토 증거를 재사용했다.
- R-001/002: 저장소 접근·만료 제거·확장은 전담 실행 스레드에만 연결돼 있고 HTTP 해석·거부 경계에는 저장소 직접 호출이 없음을 실제 소스와 위 실행 기록으로 대조했다. 자리 획득/반환·요청별 완료·실패 전파·정리·배출 경계를 검토했다. 이 두 항목은 실행 사례 수에 포함하지 않는다.

### 판정과 남는 경계

`REQ-05-001`~`005`의 이번 HTTP 동시성 범위는 **통과**다. 초기 3개 결함 해소와 남은 단계 인수 경계를 검증했으며 제품 수정이 필요한 잔존 차단 결함은 발견하지 못했다.

60초·8클라이언트의 제한된 반복 시험은 운영 시간 전체나 모든 실패 조합의 안전성을 증명하지 않는다. 반환하지 않는 저장소 연산, 강제 프로세스 종료의 복구, 저장소 직접 병렬 호출, Optional 영속성은 기존 비보장/비범위다. 네트워크 단절과 제출이 겹치면 적용 여부를 클라이언트가 단정할 수 없다. 6단계의 원본 API 포함 전체 시나리오·캐시 미사용/미스/히트 성능 비교는 별도이며 이번 통과로 대신하지 않는다. 다음 단계의 조건을 정할 수 있는 상태이나 자동 착수하지 않는다.
