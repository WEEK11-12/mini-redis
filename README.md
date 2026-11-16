# Mini Redis

미니 Redis 제작 프로젝트입니다.

## 프로젝트 문서

- [과제 원문](docs/assignment.md)
- [문서·코드·진행 컨벤션](docs/conventions.md) — 초기안, 사용자 검토 대기
- [구현 단위 가이드](docs/plans/implementation-units.md) — 작업 순서 제안
- [단계별 요구사항 색인](docs/iterations/README.md) — 단위별 명세·ID 찾아보기
- [진행 현황](docs/plans/progress.md) — 현재 위치·다음 확인 지점
- [1단계 목표·범위·공유 계약](docs/iterations/01-scope-and-contract/overview.md) — 사용자 확인 완료, 구현 전제
- [2단계 해시 테이블 저장소](docs/iterations/02-hash-table/overview.md) · [요구사항 명세](docs/iterations/02-hash-table/requirements.md) — 범위 확인, 설계 선택 중; 구현·테스트 미실시
- [결정 기록](docs/decisions/README.md)
- [Redis 학습 목차](docs/study/00-overview.md)

## 현재 출발점

가벼운 범용 인메모리 캐시 서비스를 목표로 하며, 과제의 Optional 항목을 제외한 요구를 구현 범위에 포함합니다. 여러 애플리케이션 서버에서 공통으로 접근하는 사용 장면을 상정하고 [Python·HTTP API](docs/decisions/0002-python-http-interface.md)를 채택했습니다. [1단계 공유 계약](docs/iterations/01-scope-and-contract/overview.md)과 [2단계 저장소](docs/iterations/02-hash-table/overview.md)의 요구사항 범위를 확인했고, 현재 2단계 설계 선택지를 검토하고 있습니다. 구현·테스트 결과는 아직 없습니다.

문서는 작성자가 아니라 독자와 목적을 기준으로 구분합니다. 사람이 참고하는 문서는 `docs/`에서 Git으로 관리하고, 에이전트 전용 진입 안내(`AGENTS.md`)와 작업 맥락(`.agent/`)은 Git에서 제외합니다. 로컬 안내가 없는 환경에서는 컨벤션 문서의 협업 규칙을 기준으로 다시 생성합니다.