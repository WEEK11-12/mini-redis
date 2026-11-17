# Mini Redis

미니 Redis 제작 프로젝트입니다.

## 프로젝트 문서

처음 읽을 때는 **[전체 진행 현황](docs/plans/progress.md) → 해당 단계의 `overview.md` → 필요한 상세 문서** 순서가 간단하다. 2단계의 요구사항·설계·테스트 케이스·구현·검증 파일과 서로의 관계는 [2단계 문서 길잡이](docs/iterations/02-hash-table/overview.md#이-단계의-문서-길잡이)에 모았다. 단계마다 같은 이름의 문서를 같은 역할로 사용한다(코드가 없는 단계는 필요한 문서만 둔다).

- **기준:** [과제 원문](docs/assignment.md)은 주어진 요구, [결정 기록](docs/decisions/README.md)은 단계 간 공유할 확정 선택, [컨벤션](docs/conventions.md)은 운영 규칙이다.
- **계획과 현황:** [구현 단위 가이드](docs/plans/implementation-units.md)는 작업 순서 제안, [단계별 산출물 가이드](docs/plans/iteration-deliverables.md)는 각 파일의 작성 기준, [진행 현황](docs/plans/progress.md)은 실제 상태다. 계획은 완료 증거가 아니다.
- **단계별 결과:** [요구사항 색인](docs/iterations/README.md)에서 명세를 찾고, [1단계 공유 계약](docs/iterations/01-scope-and-contract/overview.md), [2단계 저장소](docs/iterations/02-hash-table/overview.md), [3단계 HTTP 연결](docs/iterations/03-http-api/overview.md), [4단계 만료·무효화](docs/iterations/04-expiration-invalidation/overview.md)의 `overview.md`에서 해당 단계 문서로 이동한다. 개념 학습 자료는 [Redis 학습 목차](docs/study/00-overview.md)에 분리돼 있다.

링크에는 가능하면 **역할과 실제 파일명**을 함께 표시한다. 예: [검증 기록 (`verification.md`)](docs/iterations/02-hash-table/verification.md). 여기에는 테스트 실행 결과가 있고, [테스트 케이스 (`test-cases.md`)](docs/iterations/02-hash-table/test-cases.md)에는 구현 전 계획이 있다.

## 현재 출발점

가벼운 범용 인메모리 캐시 서비스를 목표로 하며, 과제의 Optional 항목을 제외한 요구를 구현 범위에 포함합니다. 여러 애플리케이션 서버에서 공통으로 접근하는 사용 장면을 상정하고 [Python·HTTP API](docs/decisions/0002-python-http-interface.md)를 채택했습니다. 1~3단계의 각 범위와 [4단계 만료·무효화](docs/iterations/04-expiration-invalidation/overview.md)의 구현·제한 독립 검토를 완료했습니다. 단계별 테스트 실행 시점, 첫 검토의 수정 요청과 재검토 판정은 [4단계 검증 기록](docs/iterations/04-expiration-invalidation/verification.md)에 있습니다. 동시성 방어와 전체 성능 비교는 후속 단계입니다. 이 상태 설명은 검토된 제품·테스트 소스 snapshot 이후 갱신했습니다.

저장소 루트에서 Python 3으로 다음 명령을 각각 실행해 현재 단계의 테스트를 확인할 수 있습니다. Mini Redis·원본 API·one-shot 클라이언트 실행 명령은 [3단계 구현 기록](docs/iterations/03-http-api/implementation.md#실행-방법)에 있습니다.

```sh
python3 -m unittest discover -s tests -p 'test_http_api.py' -q
python3 -m unittest discover -s tests -p 'test_store.py' -q
python3 -m unittest discover -s tests -p 'test_expiration_store.py' -q
python3 -m unittest discover -s tests -p 'test_expiration_http.py' -q
```

문서는 작성자가 아니라 독자와 목적을 기준으로 구분합니다. 사람이 참고하는 문서는 `docs/`에서 Git으로 관리하고, 에이전트 전용 진입 안내(`AGENTS.md`)와 작업 맥락(`.agent/`)은 Git에서 제외합니다. 로컬 안내가 없는 환경에서는 컨벤션 문서의 협업 규칙을 기준으로 다시 생성합니다.