# Mini Redis

미니 Redis 제작 프로젝트입니다.

## 프로젝트 문서

- [과제 원문](docs/assignment.md)
- [문서·코드·진행 컨벤션](docs/conventions.md) — 초기안, 사용자 검토 대기
- [구현 단위 가이드](docs/plans/implementation-units.md) — 제안, 범위·기술 선택 전
- [진행 현황](docs/plans/progress.md) — 현재 위치·다음 확인 지점
- [결정 기록](docs/decisions/README.md)
- [Redis 학습 목차](docs/study/00-overview.md)

## 현재 출발점

Redis 이론 학습을 마쳤고 구현 단위 가이드를 제안 상태로 정리했습니다. 기술 스택·구현 범위·설계는 아직 결정하지 않았으며 구현 코드도 없습니다. 가이드와 학습 기록의 예시를 확정된 기능 요구사항으로 간주하지 않습니다.

문서는 작성자가 아니라 독자와 목적을 기준으로 구분합니다. 사람이 참고하는 문서는 `docs/`에서 Git으로 관리하고, 에이전트 전용 진입 안내(`AGENTS.md`)와 작업 맥락(`.agent/`)은 Git에서 제외합니다. 로컬 안내가 없는 환경에서는 컨벤션 문서의 협업 규칙을 기준으로 다시 생성합니다.