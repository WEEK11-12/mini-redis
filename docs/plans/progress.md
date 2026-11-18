# Mini Redis 진행 현황

- 문서 상태: 현황 기록 중 — 5단계 TC 문서 검토·테스트 코드 작성, 구현·실행 검증 전
- 확인일: 2026-11-18 (KST)
- 목적: 전체 진행 흐름, 현재 작업, 막힌 결정과 검증 근거를 함께 확인한다. 일정표나 완료 예상표가 아니다.
- 기준: [과제 원문](../assignment.md), [구현 단위 가이드](implementation-units.md), [사용자 주도 진행 원칙](../decisions/0001-project-workflow.md)

## 현재 위치

- **완료로 확인된 것:** Redis 이론 학습, 공유 구현 단위 가이드 작성. 학습과 가이드 작성은 구현·테스트 완료가 아니다.
- **현재 작업 단위:** 1~3단계는 각각의 범위에서 완료했다. 4단계 만료·무효화도 [구현](../iterations/04-expiration-invalidation/implementation.md)과 [자체·독립 검증](../iterations/04-expiration-invalidation/verification.md)을 거쳐 이번 범위에서 승인됐다. 5단계는 [범위](../iterations/05-concurrency/requirements.md) 확정·[설계](../iterations/05-concurrency/design.md) 전체 검토·[TC 문서](../iterations/05-concurrency/test-cases.md) 제한 승인 및 테스트 코드 작성 단계다. 일부 RED·회귀 대조만 [검증 기록](../iterations/05-concurrency/verification.md)에 남겼고 제품 구현·전체 실행은 전이다.
- **다음 확인 지점:** 5단계 구현 및 TC 실행·독립 검토, 이후 6단계 전체 통합·성능 검증. 고정 포트 수동 시연은 미실시다.
- **구현·테스트 근거:** [2단계 검증](../iterations/02-hash-table/verification.md), [3단계 검증](../iterations/03-http-api/verification.md), [4단계 검증](../iterations/04-expiration-invalidation/verification.md)은 각 범위의 실행·독립 판정을 구분해 기록한다.

## 전체 흐름

`전체 경계·공유 계약 확인` → `각 단위에서 요구사항 정의 → 설계·검토 → TC 작성 → 구현·단위 테스트 → 기존 부분과 연결 확인` 반복 → `전체 기능·통합 테스트와 성능 비교`

전체 설계를 처음에 완성하지 않는다. 외부 인터페이스, 저장소 연산의 의미, 책임 경계와 만료·동시성의 영향만 먼저 드러내고, 내부 설계는 해당 단위에서 구체화한다. 단위 사이의 연결 확인을 마지막까지 미루지 않되, 마지막에 전체 흐름을 다시 검증한다. 실패가 나오면 해당 요구사항·설계·구현 단위로 돌아간다.

## 작업 단위 현황

| 단위 | 현재 상태 | 다음 확인할 결과 | 실제 근거 |
| --- | --- | --- | --- |
| 1. 최소 범위·공유 인터페이스 | 완료 — 과제 대응·최소 경계 확정 | 2단계에서 기본 계약 적용 | [1단계 범위·체크리스트](../iterations/01-scope-and-contract/overview.md), [D-0002](../decisions/0002-python-http-interface.md), [D-0003](../decisions/0003-http-response-contract.md); 구현·테스트 근거 없음 |
| 2. 해시 테이블 저장소 | 완료 — 공식 단위 TC 24개 통과·독립 검토 승인 | 3단계 연결 시 저장소 회귀 확인 | [단계 문서 길잡이](../iterations/02-hash-table/overview.md#이-단계의-문서-길잡이), [구현 기록 (`implementation.md`)](../iterations/02-hash-table/implementation.md), [검증 기록 (`verification.md`)](../iterations/02-hash-table/verification.md); HTTP·TTL·동시성은 미포함 |
| 3. 외부 사용·API 응답 재사용 | 완료 — 최신 HTTP 32개·저장소 24개 통과, 독립 범위 승인 | 4단계 만료·무효화에서 기존 계약 연결 | [3단계 구현 기록](../iterations/03-http-api/implementation.md), [검증 기록](../iterations/03-http-api/verification.md); 고정 포트 수동 시연 미실시 |
| 4. 만료·무효화 | 완료 — 최초 결함 수정 뒤 제한 독립 재검토 통과 | 5단계 동시성 검토에서 새 상태 변경 경로 확인 | [단계 개요](../iterations/04-expiration-invalidation/overview.md), [구현](../iterations/04-expiration-invalidation/implementation.md), [검증](../iterations/04-expiration-invalidation/verification.md); 상태 문서는 검토 snapshot 이후 갱신 |
| 5. 동시성 점검·방어 | 진행 중 — TC 문서 제한 승인·테스트 코드 작성, 구현·전체 검증 전 | 설계에 따른 구현과 동기화 TC 실행·독립 검토 | [단계 개요](../iterations/05-concurrency/overview.md), [테스트 케이스](../iterations/05-concurrency/test-cases.md), [부분 검증 기록](../iterations/05-concurrency/verification.md); 기존 순차 서버의 초점 RED만 확인 |
| 6. 전체 통합·성능 검증 | 대기 — 실행 가능한 사례 선행 | 전체 흐름의 실행 결과, 동일 조건의 비교 결과와 한계 | 없음 |

이 표의 ‘다음 확인할 결과’는 **완료 조건의 제안**이지 이미 얻은 결과가 아니다. 단위 2~5의 진행 중에도 새 연결부가 생기면 간단한 통합 확인을 하고, 실제 명령·조건·결과를 해당 단위의 기록에 남긴다. 영속성은 [과제 원문](../assignment.md)의 선택 항목으로, 현재 구현 범위에 넣지 않았다. 제외 확정도 아니다.

## 미결정 사항과 막힘

- **바로 필요한 확인:** 5단계 설계에 따른 실제 구현과 TC 실행·검토, 6단계 성능 비교 조건.
- **해당 단위에서 구체화:** 5단계 전달 채널의 구체적 구성·타임아웃 초 값과 시험 접점, 6단계 성능 비교 조건.
- **현재 확인 지점:** 4단계 TTL·무효화는 독립 검토 범위 승인. 5단계 실행 경계 계약은 채택됐으나 실제 구현은 기존 순차 서버 그대로이며 배포 형태는 후속 확인 대상이다.

## 갱신 방법

1. 작업 단위에 들어갈 때 [공통 진행 체크리스트](implementation-units.md#진행-체크리스트)를 바탕으로 해당 `overview.md`의 실행 체크리스트를 먼저 작성하고, 이번 단위의 범위·완료 조건을 확정한다. 상태는 `착수 전/대기 → 진행 중 → 결과 검토 대기 → 완료`로 관리하며 필요하면 `중단`을 표시한다.
2. 구현 단위의 요구사항은 별도 `requirements.md`에 ID·인수 조건으로 관리한다. 구현 전 TC와 구현·검증 결과는 [단계별 산출물 가이드](iteration-deliverables.md)에 따라 필요한 문서에 남기고, 이 현황판에는 근거 링크만 둔다.
3. 테스트가 있는 단위는 실제 실행 명령·조건·결과를 기록하고 범위 확정과 실행 검증을 구분한다. 1단계처럼 구현 전인 단위는 계약 확정으로 판단하며, 테스트가 없는 것을 테스트 통과로 표현하지 않는다.
4. 새로운 결정이 확정되면 [결정 기록](../decisions/README.md)에 남긴다. 매 단위가 끝날 때 다음 단위의 선행 조건·막힘·우선순위를 재확인한다. 단순 수정에는 불필요한 문서를 늘리지 않는다.
