# 구현 통합 안내

- 상태: 현재 코드의 구성·실행 경로를 읽기 위한 요약. 실제 완료/실행 판정은 단계별 검증 기록을 따른다.
- 근거: [단계별 진행·결과](iterations/README.md), [요구사항](requirements.md), [설계](design.md)

## 코드 경로와 역할

| 경로 | 구현된 역할과 변화 | 상세 기록 |
| --- | --- | --- |
| `mini_redis/store.py` | 직접 구현한 `HashTableStore`: 64비트 다항 해시, 버킷별 리스트 체인·전체 키 비교, 확장 시 재해싱, 실패 전 준비 후 상태 교체. 4단계에서 선택적 만료 기한·주입 가능한 단조 시간원, `set_ttl`·`clear_ttl`·`sweep_expired`, 접근 시 만료 제거를 추가했다. 일반 `set`은 TTL을 해제한다. | [2단계 구현](iterations/02-hash-table/implementation.md) · [4단계 구현](iterations/04-expiration-invalidation/implementation.md) |
| `mini_redis/http_api.py` | 저장소 공개 연산을 HTTP 요청·응답에 연결하고 키·경로·본문·오류를 검증한다. 4단계에서 TTL 경로와 유휴 정리를 추가했고, 5단계에서 HTTP 요청 스레드와 단일 명령 실행 스레드·큐로 경계를 바꿨다. 접수 한도·배출·종료 경계를 둔다. 초기 3단계의 순차 서버 기록은 변경 당시의 기록이다. | [3단계 구현](iterations/03-http-api/implementation.md) · [4단계 구현](iterations/04-expiration-invalidation/implementation.md) · [5단계 구현](iterations/05-concurrency/implementation.md) |
| `examples/origin_api.py`, `examples/client.py` | 별도 프로세스의 원본 고정 응답 API와 캐시 미스일 때만 원본을 호출·저장하는 one-shot 클라이언트. `404 KEY_NOT_FOUND` 이외의 캐시 실패를 히트나 미스로 위장하지 않는다. | [3단계 구현·실행 방법](iterations/03-http-api/implementation.md#실행-방법) |
| `examples/benchmark.py` | 6단계의 미사용·미스·히트 순차 측정 경로. 측정 조건과 원자료·실행 결과는 검증 기록에서 확인한다. | [6단계 검증](iterations/06-integration-performance/verification.md#3-성능-비교-실행) |
| `tests/` | 저장소·HTTP·만료의 공식 테스트. 5단계 동시성 검증은 원본 테스트의 임시 접점을 로컬 scratch 복사본에 계측해 실행했으며, 원본 runner를 무보정으로 Green이라 주장하지 않는다. | [2단계 검증](iterations/02-hash-table/verification.md) · [3단계 검증](iterations/03-http-api/verification.md) · [4단계 검증](iterations/04-expiration-invalidation/verification.md) · [5단계 검증](iterations/05-concurrency/verification.md) |

## 실행과 한계

실제 서버·원본 API·클라이언트 시작 명령은 [3단계 실행 방법](iterations/03-http-api/implementation.md#실행-방법)에, 전체 사용 사례·성능 측정 환경과 실행 명령은 [6단계 검증](iterations/06-integration-performance/verification.md)에 있다. 각 단계의 `implementation.md`는 그 시점의 코드 변경과 구현 선택을, `verification.md`는 실행 명령·관찰 결과를 기록한다. 1단계는 코드가 없는 계약 단위이고 6단계는 새 기능 구현 단위가 아니므로 해당 단계의 `implementation.md`를 억지로 만들지 않는다. 고정 포트 수동 시연, Optional 영속성 및 배포는 완료 근거가 없다.
