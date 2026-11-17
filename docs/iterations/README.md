# 단계별 요구사항 색인

각 단계의 `requirements.md`를 모아 찾는 입구다. 요구사항 본문은 여기 복사하지 않고 원문 링크와 ID 범위만 유지한다. ID는 단계별 `REQ-<단계>-<일련번호>`로 고정하며, 구현·테스트 결과는 각 단계 문서에서 연결한다.

| 단계 | 요구사항 명세 | ID 범위 | 상태 |
| --- | --- | --- | --- |
| 1. 범위·공유 계약 | [1단계 계약](01-scope-and-contract/overview.md) | 별도 요구사항 ID 없음 | 범위·계약 확정; 후속 단계의 근거 |
| 2. 해시 테이블 저장소 | [2단계 요구사항 명세](02-hash-table/requirements.md) | `REQ-02-001`~`REQ-02-008` | 범위 확정, 단위 검증 완료 ([단계 문서 길잡이](02-hash-table/overview.md#이-단계의-문서-길잡이)) |
| 3. 외부 HTTP 사용·API 응답 재사용 | [3단계 요구사항 명세](03-http-api/requirements.md) | `REQ-03-001`~`REQ-03-008` | 완료 — HTTP 32개·저장소 24개 통과, 독립 범위 승인 ([단계 개요](03-http-api/overview.md)) |
| 4. 만료·명시적 무효화 | [4단계 요구사항 명세](04-expiration-invalidation/requirements.md) | `REQ-04-001`~`REQ-04-006` | 이번 범위 완료 — 최초 결함 수정 후 제한 독립 재검토 통과 ([단계 개요](04-expiration-invalidation/overview.md), [검증 기록](04-expiration-invalidation/verification.md)) |
| 5. 동시성 위험 점검·방어 | [5단계 요구사항 명세](05-concurrency/requirements.md) | `REQ-05-001`~`REQ-05-005` | HTTP 경로의 범위·인수 조건 확정, 설계·검증 전 ([단계 개요](05-concurrency/overview.md), [D-0007](../decisions/0007-single-thread-command-execution.md)) |
| 6. 전체 통합·성능 검증 | 해당 단위 착수 시 작성 | 미부여 | 미착수 |

새 단위를 시작할 때 같은 형식의 `requirements.md`를 작성하고 이 표에 실제 파일·ID 범위만 추가한다. 1단계는 공유 범위·계약 문서이므로 기존 문서에 소급하여 임의의 ID를 부여하지 않는다.
