# 4단계 검증 기록 — 만료와 무효화

- 상태: 수정 후 제한 독립 재검토 통과 — 4단계 검토 범위 승인
- 조건: 2026-11-18 KST, 저장소 루트, `python3` 표준 `unittest`; 실제 HTTP 서버는 테스트의 임시 포트 사용
- 기준: [TC 목록](test-cases.md), [구현 기록](implementation.md)

| 범위 | 실제 명령 | 결과 | 미확인 |
| --- | --- | --- | --- |
| TC-04-U-001~014, TC-04-I-001~015의 현재 실행 코드 | `python3 -m unittest discover -s tests -p 'test_expiration*.py' -q` | 29개 실행, OK (코드 마지막 수정 전) | I-013의 요청·정리 비중첩/지연 주기 보상 호출 없음, I-014의 진단 실패 격리·정확한 다음 주기 간격은 실행 단언 미구현. 독립 판정 아님 |
| TC-04-U-001~014 (최종 저장소 시각 기준 변경 이후) | `python3 -m unittest discover -s tests -p 'test_expiration_store.py' -q` | 14개 실행, OK | 독립 판정 대기 |
| TC-04-I-001~015 (최종 저장소 시각 기준 변경 이후) | `python3 -m unittest discover -s tests -p 'test_expiration_http.py' -q` | 15개 실행, OK | I-013·014의 일부 세부 조건은 실행 단언 미구현 |
| 2단계 기존 저장소 회귀 | `python3 -m unittest discover -s tests -p 'test_store.py' -q` | 24개 실행, OK (마지막 저장소 시각 기준 수정 전) | 최종 전체 회귀는 독립 검토에 인계 |
| 3단계 기존 HTTP 회귀 | `python3 -m unittest discover -s tests -p 'test_http_api.py' -q` | 32개 실행, OK (마지막 저장소 시각 기준 수정 전) | 최종 전체 회귀는 독립 검토에 인계 |
| 문법·diff | `python3 -m py_compile mini_redis/store.py mini_redis/http_api.py; git diff --check` | 통과 | 정적 타입 검사 도구 미설정 |

`test-cases.md`의 U/I 번호는 테스트 파일의 `test_u_...`/`test_i_...`에 대응한다. 위 29개 실행 결과만으로 목록의 세부 조건 전부를 통과했다고 판정하지 않는다. 최초 독립 검토는 아래 결함으로 수정 요청했다.

## 독립 검토 수정 요청과 제한 재점검

최초 독립 검토 판정은 **수정 요청**이다. 만료 항목 제거에서 버킷을 먼저 확정하고 `_size -= 1` 중 실제 `MemoryError`가 나면 물리 항목 수가 불일치하는 결함이 보고됐다. 검토자는 **수정 전 제출본**의 기존 저장소 24개·HTTP 32개 회귀와 보완 5개를 실행해 통과했고, 정리 진단 실패·요청/정리 비중첩·보상 실행 없음도 보완 확인했다. 이는 최초 제출본의 승인 판정이 아니다.

`mini_redis/store.py`의 접근 만료 제거·주기 정리·일반 삭제에서 새 카운터 계산을 버킷 확정 전에 끝내도록 수정했다. `tests/test_expiration_store.py`에 카운터 계산 실패 시 버킷·수 보존 및 후속 재시도 회귀 한 건을 추가했다. 수정 후 저장소 루트에서 `python3 -m unittest discover -s tests -p 'test_expiration_store.py' -q` **15개 OK** (추가 전 14개 OK도 관찰), `python3 -m unittest discover -s tests -p 'test_store.py' -q` 24개 OK, `python3 -m unittest discover -s tests -p 'test_expiration_http.py' -q` 15개 OK, `git diff --check` 통과. 검토자의 격리 재현 `allocation_probe.py`를 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" python3 <probe> <get|exists|delete|set_ttl|clear_ttl|sweep_expired> 0`으로 각 독립 프로세스에 실행했다. 여섯 경로 모두 `MemoryError` 후 정리 재시도에서 1개 제거했고 결과 수 299로 복원됐다. 그 probe의 `actual=300`은 **재시도 전**, `size=299`·`target_present=false`·`counter_consistent=false`는 **재시도 후** 평가되어 혼합 시점의 `counter_consistent`를 단독 판정에 사용하지 않았다. 결함 해소의 독립 판정은 아래 제한 재검토 결과에 기록했다.

## 제한 재검토 판정과 범위

독립 검토자는 수정된 계산/커밋 경계와 새 회귀 oracle을 검토하고 **통과**를 판정했다. 격리된 CPython 단일 할당 실패 실험에서 만료 경로 6개와 일반 삭제 1개 각각 실패 주입·정상 대조군을 실행해 총 14개 시나리오가 모두 PASS였다. 실패 직후 `_size=300`·물리 수 300·대상 값/기한/버킷 배치가 보존됐고, 실패 해제 후 같은 공개 연산으로 재시도하면 `_size=299`·물리 수 299가 됐다. 집계 JSON의 14개 항목과 모두 `PASS`임을 별도 확인했고, 검토 기록의 저장소·HTTP·추가 테스트 소스 해시를 현재 작업 트리와 대조해 일치했다. 신규 검토에서 기존 24개 저장소·32개 HTTP 및 보완 5개를 통과시킨 증거는 최초 검토 결과이고, 제한 재검토에서는 반복 실행하지 않았다. 자체 TTL 저장소 15개·TTL HTTP 15개는 구현자 실행 증거다.

이 판정은 이번 4단계 검토 범위에 한정한다. 동시성 방어(5단계), 전체 종단 간·성능 비교(6단계), 영속성, 고정 포트 수동 시연, 임의의 시스템 메모리 고갈 전수 검증은 미실시다. 이 절과 이후 상태 문서 갱신은 **검토된 제품·테스트 소스 snapshot 이후의 문서 변경**이며 제품 코드는 변경하지 않았다.
