# 설계 통합 안내

- 상태: 채택된 경계와 단계별 설계의 요약. 세부 알고리즘·예외는 링크의 원문을 따른다.
- 근거: [1단계 공유 계약](iterations/01-scope-and-contract/overview.md), [결정 목록](decisions/README.md), [단계별 설계](iterations/README.md)

## 전체 구조와 사용 흐름

`외부 클라이언트 → HTTP 접수·입력 검증 → 명령 큐 → 단일 명령 실행 스레드 → HashTableStore`가 캐시 경로다. 명령 실행 스레드는 만료 정리도 담당한다. 예제에서는 별도 원본 API가 SQLite 파일 DB에서 조회한 응답을 첫 캐시 미스 때 가져와 저장하고, 이후 캐시 히트에서는 원본 호출 없이 값을 재사용한다. [3단계 설계](iterations/03-http-api/design.md), [5단계 설계](iterations/05-concurrency/design.md)

| 경계 | 설계와 중요한 선택 | 더 자세히 |
| --- | --- | --- |
| 공유 계약 | Python 기반 HTTP 서비스. 문자열 키·값, 빈 값과 미존재 분리, 기본 연산별 상태/본문, 공통 오류 본문과 `Cache-Control: no-store`. HTTP 키에는 슬래시를 허용하지 않고 실제 외부 허용 문자는 ASCII 영문·숫자·`-_.~`로 제한한다. | [D-0002](decisions/0002-python-http-interface.md) · [D-0003](decisions/0003-http-response-contract.md) · [D-0004](decisions/0004-http-key-no-slash.md) · [D-0005](decisions/0005-http-api-boundary.md) |
| 저장소 | `HashTableStore`가 버킷별 리스트와 전체 키 비교로 충돌을 구분한다. 저장·조회·존재 확인·삭제의 순차 호출을 전제로 하며, 새 키로 적재율 1 초과 시 버킷 배열을 두 배로 확장·재해싱한다. 준비 중 실패 시 공개 상태를 보존하는 방식을 둔다. | [2단계 설계](iterations/02-hash-table/design.md) |
| HTTP 연결 | 요청 경로·메서드·쿼리와 JSON 본문을 분류한 뒤 저장소 공개 연산에 연결한다. PUT 본문은 문자열 `value` 하나만 허용하며 선언 길이는 64 KiB 이하. 미지원 메서드·입력 오류·내부 실패를 구별한다. 예제 원본 API와 별도 클라이언트의 재사용 흐름은 공유 캐시 계약과 구별한다. | [3단계 설계](iterations/03-http-api/design.md) · [D-0005](decisions/0005-http-api-boundary.md) |
| 만료·무효화 | 저장소가 만료 기한을 관리하고 접근 시 만료 항목을 제거하며 유휴 시에도 정리한다. TTL 설정/제거는 기존 PUT과 별도이고, 일반 PUT은 이전 TTL을 해제한다. DELETE는 무효화다. 저장과 TTL 설정의 두 요청 사이 원자성은 보장하지 않는다. | [4단계 설계](iterations/04-expiration-invalidation/design.md) · [D-0006](decisions/0006-ttl-invalidation-contract.md) |
| 동시성 | 3단계의 순차 HTTPServer 실행 구조는 5단계에 변경됐다. HTTP 요청 해석은 병렬 가능하지만 조회(만료 제거 포함)·변경·정리는 하나의 명령 실행 스레드에서 순차 처리한다. 한도 초과/배출 중 새 접수에는 좁은 거부 예외가 있다. 직접 병렬 저장소 호출의 안전성은 범위 밖이다. | [5단계 설계](iterations/05-concurrency/design.md) · [D-0007](decisions/0007-single-thread-command-execution.md) |
| 최종 검증 | 6단계는 새 설계 모듈이 아니라 연결된 사용 흐름과 캐시 미사용·미스·히트의 순차 클라이언트 지연시간을 확인한다. 원본은 처음 고정 응답이었으나 과제 의도(서버 DB 조회 대 메모리 캐시 읽기)에 맞춰 `sqlite3` 파일 DB 기본 키 조회로 바꿨다. 양쪽 모두 로컬 HTTP를 거치는 전체 흐름 비교이고 DB 조회가 OS·SQLite 캐시에서 처리될 수 있다. 인위적 원본 지연이나 동시 부하 측정은 제외한다. | [6단계 개요](iterations/06-integration-performance/overview.md) · [검증 기록](iterations/06-integration-performance/verification.md) |

결정 기록은 선택의 이유·영향을 설명하고, 설계 원문은 계약의 상세·실패 흐름·검증 지점을 설명한다. 이 요약은 각 시점의 설계를 한데 읽기 위한 것이며 초기 순차 HTTP 구조를 현재 실행 구조로 오인하지 않도록 구분한다.
