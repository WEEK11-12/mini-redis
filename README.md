# Mini Redis

미니 Redis 제작 프로젝트입니다.

## 프로젝트 문서

처음 읽을 때는 **[전체 진행 현황](docs/plans/progress.md) → 해당 단계의 `overview.md` → 필요한 상세 문서** 순서가 간단하다. 2단계의 요구사항·설계·테스트 케이스·구현·검증 파일과 서로의 관계는 [2단계 문서 길잡이](docs/iterations/02-hash-table/overview.md#이-단계의-문서-길잡이)에 모았다. 단계마다 같은 이름의 문서를 같은 역할로 사용한다(코드가 없는 단계는 필요한 문서만 둔다).

- **기준:** [과제 원문](docs/assignment.md)은 주어진 요구, [결정 기록](docs/decisions/README.md)은 단계 간 공유할 확정 선택, [컨벤션](docs/conventions.md)은 운영 규칙이다.
- **계획과 현황:** [구현 단위 가이드](docs/plans/implementation-units.md)는 작업 순서 제안, [단계별 산출물 가이드](docs/plans/iteration-deliverables.md)는 각 파일의 작성 기준, [진행 현황](docs/plans/progress.md)은 실제 상태다. 계획은 완료 증거가 아니다.
- **단계별 결과:** [요구사항 색인](docs/iterations/README.md)에서 명세를 찾고, [1단계 공유 계약](docs/iterations/01-scope-and-contract/overview.md), [2단계 저장소](docs/iterations/02-hash-table/overview.md), [3단계 HTTP 연결](docs/iterations/03-http-api/overview.md)의 `overview.md`에서 해당 설계·TC·구현·검증 기록으로 이동한다. 개념 학습 자료는 [Redis 학습 목차](docs/study/00-overview.md)에 분리돼 있다.

링크에는 가능하면 **역할과 실제 파일명**을 함께 표시한다. 예: [검증 기록 (`verification.md`)](docs/iterations/02-hash-table/verification.md). 여기에는 테스트 실행 결과가 있고, [테스트 케이스 (`test-cases.md`)](docs/iterations/02-hash-table/test-cases.md)에는 구현 전 계획이 있다.

## 현재 출발점

가벼운 범용 인메모리 캐시 서비스를 목표로 하며, 과제의 Optional 항목을 제외한 요구를 구현 범위에 포함합니다. 여러 애플리케이션 서버에서 공통으로 접근하는 사용 장면을 상정하고 [Python·HTTP API](docs/decisions/0002-python-http-interface.md)를 채택했습니다. [1단계 공유 계약](docs/iterations/01-scope-and-contract/overview.md)과 [2단계 저장소](docs/iterations/02-hash-table/overview.md)를 해당 범위에서 완료했습니다. 2단계 저장소는 단위 TC 24개를 통과하고 독립 검토에서 승인됐습니다. [3단계 HTTP 연결](docs/iterations/03-http-api/overview.md)은 요구사항·설계 계약과 문서 검토까지 마쳤고 구현 전 TC를 작성할 차례입니다. HTTP 연결·TTL·동시성 및 성능 비교는 아직 구현·검증하지 않았습니다.

문서는 작성자가 아니라 독자와 목적을 기준으로 구분합니다. 사람이 참고하는 문서는 `docs/`에서 Git으로 관리하고, 에이전트 전용 진입 안내(`AGENTS.md`)와 작업 맥락(`.agent/`)은 Git에서 제외합니다. 로컬 안내가 없는 환경에서는 컨벤션 문서의 협업 규칙을 기준으로 다시 생성합니다.