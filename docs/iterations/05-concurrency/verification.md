# 5단계 검증 기록 — 테스트 코드 작성 단계

- 상태: 구현 전 테스트 코드의 부분 자체 확인과 독립 검토 지적의 제한 수정 기록; 5단계 기능 통과·테스트 코드 재검토 승인 전
- 근거: [TC 목록](test-cases.md), [요구사항](requirements.md), [설계](design.md)

## 자체 확인 (현재 순차 서버 기준)

저장소 루트에서 Python 3.14로 `tests/test_concurrency_http.py`를 작성했다. `R-001`·`R-002`는 코드 검토 항목이며 실행 테스트 수에 포함하지 않는다. 제품 코드는 바꾸지 않았다.

| 대상 | 실제 명령·조건 | 실제 결과 | 판정·한계 |
| --- | --- | --- | --- |
| 구문·발견·TC 매핑 | `python3 -m py_compile tests/test_concurrency_http.py`; `unittest.TestLoader.discover('tests', pattern='test_concurrency_http.py')`의 ID와 TC 목록 비교 | 구문 통과, 통합 TC 25개와 `test_i_001`~`025` 25개가 일대일 대응 | 수집·구문 확인일 뿐 테스트 본문 전체 실행 아님 |
| 초점 RED·기존 계약 대조 | `PYTHONPATH=tests python3 -m unittest test_concurrency_http.ConcurrencyHTTPTests.test_i_001_slow_body_does_not_block_other_client test_concurrency_http.ConcurrencyHTTPTests.test_i_005_unordered_same_key_results_are_serializable test_concurrency_http.ConcurrencyHTTPTests.test_i_017_oversize_rejected_before_body_and_no_followup -q` | 3개 실행: I-001 `TimeoutError`(느린 PUT 동안 B 처리 불가), I-005 실패(저장소 호출 스레드가 서버 루프와 동일), I-017 통과(초과 선언 본문 읽기·저장소 미접근 및 기존 오류 계약) | **1 통과·1 실패·1 오류**. 앞 두 RED는 현재 순차 서버와 설계 목표의 차이이며 5단계 동작 통과 아님. I-017은 기존 입력 경계 회귀의 제한된 대조만 확인 |
| 계측 대조 | `PYTHONPATH=tests python3 -c 'import threading; from test_concurrency_http import ObservedStore,Clock; s=ObservedStore(Clock()); [s.set(str(i),str(i)) for i in range(8)]; s.hold("rehash",None); t=threading.Thread(target=s.set,args=("ninth","9")); t.start(); assert s.entered.wait(2); assert len(s._buckets)==8; s.unblock(); t.join(2); assert not t.is_alive() and (len(s._buckets),s._size)==(16,9) and not s.overlap; q=ObservedStore(Clock()); q.hold("get","a"); w=threading.Thread(target=q.get,args=("a",)); w.start(); assert q.entered.wait(2); q.exists("b"); q.unblock(); w.join(2); assert q.overlap; print("observer positive and concurrent counterexample: OK")'` | `observer positive and concurrent counterexample: OK` | 동일 스레드 내부 중첩은 겹침으로 판정하지 않고 다른 스레드 진입은 감지; 실제 서버의 5단계 명령 경계 검증 아님 |
| 문서·작업 트리 | `git diff --check` | 통과 | 새로운 미추적 테스트·TC 파일은 Git diff 통계에 포함되지 않으므로 상태 목록에서 별도 확인 |

독립 테스트 코드 검토는 **수정 요청**이었다. I-019의 GET 계수, 제출 순서·배출 전환 관찰, I-006의 정리/확장 경합, I-005의 실제 실행 순서와 응답 대조, 종료 교착 시 테스트 무기한 대기를 제한 수정했다. 제한 재검토에서 `server_close()`의 non-daemon 요청 스레드 대기 반례가 추가로 확인되어 I-023~025의 서버 수명 전체를 자식 프로세스에서 실행하고 부모가 30초 뒤 종료·회수하도록 보완했다. 앞 표의 I-001·I-005 RED와 계측 대조는 이 수정 전 실행이며 최종 코드 재실행 결과가 아니다. 수정 후에는 AST로 통합 함수 25개 발견, 서로 다른 PUT 인자 기록·종료 watchdog 반례를 확인했다. I-005/I-017 초점 실행은 수명 격리 수정 이전에 **1 예상 RED(I-005: 저장소가 서버 루프 스레드에서 실행)·1 통과(I-017)**였다. 수명 격리 수정 후 I-023 초점 실행은 자식 프로세스의 임시 `_test_crash_executor` 부재 실패를 부모에게 전달하는 예상 RED였고, `python3 -m py_compile tests/test_concurrency_http.py`와 `git diff --check`는 통과했다. 수정 범위의 독립 재검토에서 이전 네 지적의 해소와 I-023~025 수명 격리를 각각 제한 승인받았다. 마지막 검토는 실제 `server_close()` 정지 반례에서 부모의 30초 실패 전달·자식 종료와 회수까지 확인했다. 이 판정은 TC 코드의 해당 지적에 한정되며 제품 기능·전체 TC 승인과 다르다. 이 문장 갱신은 마지막 검토 대상 소스 스냅샷 이후의 문서 변경이다.

제출 순서·수용량·오류 주입·종료·실행 시계 관찰은 **임시 시험 접점**으로 표시했다(`_test_pending_commands`, `_test_draining`, `_test_accepted_requests`, `_test_request_deadline_seconds`, `_test_submission_gate`, `_test_fail_response_write`, `_test_fail_delivery`, `_test_crash_executor`, `_test_admission_gate`). 이 이름은 제품 API가 아니며 구현 시 실제 구조에 맞추어 테스트 계측을 조정한다. 기존 코드에는 해당 접점이나 목표 전담 실행 스레드가 없다. **전체 25개 실행과 2~4단계 회귀는 미실시**다. I-019의 제출 후 단절 요청 자리 유지, I-024의 배출 중 기존 해석 요청 제출, I-025의 배출 중 정리 목표·순서, 느린 응답·거부 경계는 구현 후 별도 보완/확인 대상이다. 문서화된 TC 한 행에 여러 조건이 있는 경우 함수 발견만으로 모든 세부 조건이 검증됐다고 판단하지 않는다.
