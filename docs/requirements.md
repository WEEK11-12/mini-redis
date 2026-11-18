# 요구사항 통합 안내

- 상태: 1~6단계의 확정 범위와 검증 경로를 요약한 읽기용 문서
- 기준: [과제 원문](assignment.md), [단계별 진행·결과](iterations/README.md). 이 문서는 원문 요구사항·인수 조건이나 실행 증거를 대체하지 않는다.

## 목표와 범위

직접 구현한 해시 테이블 기반 키-값 저장소를 외부에서 사용할 수 있게 하고, 핵심 로직을 설명하며 저장·조회·삭제의 단위/기능 테스트와 API 응답 캐싱 사례·성능 비교를 수행하는 과제다. 만료 값 처리, 무효화, 동시성 구조를 다루고 서버 장애 시 영속성은 선택 항목이다. [과제 원문](assignment.md), [1단계 범위·공유 계약](iterations/01-scope-and-contract/overview.md)

| 단계 | 무엇을 충족하는가 | 상세 명세·판정 |
| --- | --- | --- |
| 1. 범위·공유 계약 | Python·HTTP 공유 캐시, 기본 키·값과 연산의 경계 확정. 별도 REQ ID나 구현 검증 없음. | [1단계 계약](iterations/01-scope-and-contract/overview.md), [D-0002](decisions/0002-python-http-interface.md), [D-0003](decisions/0003-http-response-contract.md) |
| 2. 저장소 (`REQ-02-001`~`008`) | 저장·덮어쓰기, 빈 값/미존재 구별, 존재 확인·삭제, 잘못된 입력 보존, 충돌 키의 독립성, 직접 구현과 단위 검증. | [명세](iterations/02-hash-table/requirements.md) · [TC](iterations/02-hash-table/test-cases.md) · [검증](iterations/02-hash-table/verification.md) |
| 3. HTTP·재사용 (`REQ-03-001`~`008`) | 외부 기본 연산, HTTP 입력/오류·캐시 방지 헤더, 실제 저장소 연결, 원본 API 응답의 첫 저장과 다음 호출 재사용. | [명세](iterations/03-http-api/requirements.md) · [TC](iterations/03-http-api/test-cases.md) · [검증](iterations/03-http-api/verification.md) |
| 4. 만료·무효화 (`REQ-04-001`~`006`) | TTL 설정·갱신·제거, 만료 키의 미존재 처리, 덮어쓰기의 이전 TTL 해제, DELETE 무효화, 기존 계약 회귀. | [명세](iterations/04-expiration-invalidation/requirements.md) · [TC](iterations/04-expiration-invalidation/test-cases.md) · [검증](iterations/04-expiration-invalidation/verification.md) |
| 5. 동시성 (`REQ-05-001`~`005`) | 병렬 HTTP 접수·해석과 단일 명령 실행 스레드, 동일 키·만료 경합의 유효한 결과, 접수 전 거부 경계. 저장소 직접 병렬 호출은 보장하지 않음. | [명세](iterations/05-concurrency/requirements.md) · [TC](iterations/05-concurrency/test-cases.md) · [검증](iterations/05-concurrency/verification.md) |
| 6. 전체 사용·성능 | 새 기능 명세/REQ ID 없이 기존 요구와 과제의 품질 항목을 외부 사용 흐름·순차 지연시간 비교·설명 가능 여부로 확인. | [범위·조건](iterations/06-integration-performance/overview.md) · [TC](iterations/06-integration-performance/test-cases.md) · [검증](iterations/06-integration-performance/verification.md) |

## 이어지는 계약과 완료 범위

저장소의 빈 문자열은 존재하는 값이며, HTTP 조회의 미존재/만료는 `404 KEY_NOT_FOUND`, 존재 확인의 미존재는 `200`·`false`다. HTTP 키 제한은 저장소 전체 키 제한이 아니다. TTL은 별도 연산이고 일반 PUT은 기존 TTL을 해제하며 DELETE가 명시적 무효화다. 수용된 HTTP 명령은 하나의 실행 스레드에서 처리한다. 정확한 요청·응답은 [D-0003](decisions/0003-http-response-contract.md), [D-0005](decisions/0005-http-api-boundary.md), [D-0006](decisions/0006-ttl-invalidation-contract.md), [D-0007](decisions/0007-single-thread-command-execution.md)를 따른다.

각 단계는 정해진 범위에서 완료됐다. 이것은 모든 환경의 성능 보증이나 무보정 원본 5단계 계측 시험의 통과를 뜻하지 않는다. 6단계 설명 가능 여부는 본인 확인이며 독립 구술 검증은 아니다. Optional 영속성, 고정 포트 수동 시연 및 배포는 완료 범위 밖이다. 실제 실행·한계는 [단계별 진행·결과](iterations/README.md)와 각 검증 기록에서 확인한다.
