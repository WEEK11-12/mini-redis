# 2단계 실행 기록 — 해시 테이블 저장소

- 상태: 전체 TC 실행·독립 검토 승인 (제품 소스 스냅샷 확인)
- 근거: [요구사항](requirements.md), [구현 전 TC](test-cases.md), [구현](implementation.md)
- 환경: macOS, Python 3.14.5, 저장소 루트에서 실행

| 대상 | 코드·명령 | 실제 결과 | 미확인 범위 |
| --- | --- | --- | --- |
| TC-02-U-001 RED | 구현 전 `python3 -m unittest discover -s tests -p test_store.py -k test_001 -v` | 1개 실패: `mini_redis` 모듈 부재(예상된 구현 전 실패) | 동작 검증 아님 |
| TC-02-U-001 최소 확인 | 구현 후 같은 명령 | 1개 통과 | 전체 인수 검증 아님 |
| TC-02-U-021 최소 확인 | `python3 -m unittest discover -s tests -p test_store.py -k test_021 -v` | 1개 통과 | 다른 실패 주입 지점 미확인 |
| 문법 확인 | `python3 -m compileall -q mini_redis` | 종료 코드 0 | 정적 타입 검사 도구 미설정 |
| TC-02-U-001~024 전체 | `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_store.py -v` | 검증 담당 실행: 24개 통과, 실패·미실행·skip 0 | 아래 범위 참조 |
| 보완 실패 주입·혼합 연산 | 검증 담당의 별도 `probes.py` 실행 | 49개 probe 통과(예외 주입 44, 혼합 순차 연산 15,000회) | 공식 TC 숫자에 포함하지 않음 |
| REQ-02-007 코드 경로 검토 | `mini_redis/store.py` | 독립 검토: 버킷·전체 키 비교 및 자체 해시 사용 확인, 차단 결함 없음 | 구두 설명 능력은 미평가 |

검증 담당의 실행 환경은 macOS 26.6.2 arm64, Python 3.14.5, 표준 `unittest`다. 공식 테스트 `tests/test_store.py`의 `test_001`~`test_024`는 [TC 목록](test-cases.md)의 `TC-02-U-001`~`024`와 일대일 대응하며, 각 ID 모두 통과했다. REQ-02-001~006은 해당 TC와 보완 실행, REQ-02-007은 직접 구현 코드 경로와 HTTP 없는 실행, REQ-02-008은 명령·TC 대응·결과 기록으로 확인했다. 상세한 각 TC·주입 위치·원본 로그와 검토 판정은 로컬 `.agent/handoffs/iteration-02-review.md` 및 검토자 scratch의 `review-results.json`에 남아 있다.

TC-023의 공식 검사는 확장 진입 **전**의 `MemoryError`만 확인한다. 별도 probe는 재배치 1~8번째, 새 키 반영 9번째의 실제 `_insert` 전후에 `RuntimeError`·`MemoryError`를 주입한 36가지 경계와 비확장 삽입·덮어쓰기 전후 8가지를 확인했다. 예외 전달, 기존 배열·값·항목 수·용량 유지와 이후 연산을 확인했다. 독립 검토는 제품 수정 요구 없이 승인했다. 영구 TC에 부분 재배치 실패 사례를 추가하는 것은 비차단 제안이며 아직 적용하지 않았다.

실제 물리적 메모리 고갈, 비동기 신호·강제 종료, HTTP·TTL·동시성·영속성, 성능/해시 분포 우열과 구두 설명 능력은 검증하지 않았다. 정적 타입 도구·린터는 미설정이다. 검토 시점의 제품 코드와 테스트·2단계 문서 해시가 검토 기록과 일치함을 확인했으며, 이 문서는 **검토 이후** 실행 결과를 반영한 기록이다.
