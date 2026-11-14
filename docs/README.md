# 프로젝트 문서 지도

AI는 [AGENTS](../AGENTS.md) → [WORKLOG](../WORKLOG.md) → 관련 요구·설계·테스트 순서로 읽습니다. 개발자는 프로젝트 개요와 API부터 확인하면 됩니다. 현재 main에는 구현용 문서만 있고 실행 가능한 서버는 없습니다.

| 문서 | 담당하는 정보 | 중복을 피하는 기준 |
| --- | --- | --- |
| [PROJECT](PROJECT.md) | 목표·범위·기술과 실제 구현 상태 | 세부 계약은 아래 문서로 연결 |
| [assignment](assignment.md) | 과제 원문 요구 요약 | 프로젝트 선택을 원문 요구로 바꾸지 않음 |
| [REQUIREMENTS](REQUIREMENTS.md) | 요구 ID·출처·인수 조건·미정 경계 | 제품이 무엇을 해야 하는지의 기준 |
| [DESIGN](DESIGN.md) | 역할·상태 소유·락·해시·TTL·생명주기 | 어떻게 동작시킬지의 기준 |
| [DECISIONS](DECISIONS.md) | 조건·대안·이득·비용·선택 이유 | 기존 답을 정당화하는 이유를 만들지 않음 |
| [API](API.md) | HTTP 경로·본문·응답·오류 | 외부 호출 계약의 기준 |
| [TESTING](TESTING.md) | 단위 U1~U7, 테스트 ID와 요구 추적 | 계획과 실행 결과를 구분 |
| [WORKFLOW](WORKFLOW.md) | 함께 논의·검증·리뷰·Git 반영하는 방법 | 사용자와의 진행 약속 |
| [WORKLOG](../WORKLOG.md) | 현재 단위·실제 결과·인계·다음 작업 | 다음 AI가 이어받을 상태 |
| [study/](https://github.com/jye-1123/mini-redis/blob/study-jye/study/00-overview.md) | 개념과 쉬운 예시 | 프로젝트 규격을 따로 재정의하지 않음 |

## 구조

```text
AGENTS.md             AI의 읽는 순서와 작업 경계
README.md             개발자를 위한 입구
WORKLOG.md            현재 상태와 인계
 docs/                요구·설계·API·테스트·협업 문서
학습 필기는 별도 study-jye 브랜치에서 관리
```

소스·테스트 폴더는 첫 구현 단위에서 최소 구성으로 추가합니다. 존재하지 않는 경로를 현재 구현처럼 안내하지 않습니다. 설계·규격·코드·테스트는 개인 포크 main이 기준입니다. study-jye는 학습 필기 전용입니다.

## 갱신 규칙

새 합의가 생기면 관련 요구와 설계/API를 먼저 맞추고 테스트와 WORKLOG를 연결합니다. 선택 이유는 DECISIONS에, 개념 설명은 별도 study-jye 브랜치에 둡니다. 계약 변경 시 관련 문서의 오래된 설명도 점검합니다. 숫자는 실측 전 최적값으로 표현하지 않습니다. 최신 사용자 합의와 문서가 다르면 차이를 확인하고 고칩니다.
