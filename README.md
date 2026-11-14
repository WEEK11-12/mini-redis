# Mini Redis

직접 만든 해시 테이블에 문자열 키·값을 보관하고, HTTP API로 저장·조회·삭제·TTL을 제공하는 작은 메모리 서버입니다.

**현재 상태:** U1~U4 저장소·TTL·능동 청소 작업자를 구현하고 현재 자동 테스트 44개를 커밋 전 재실행해 통과했습니다. U5도 다른 키 요청·확장·청소 겹침의 필수 검증을 통과했습니다. HTTP 서버는 아직 없습니다. [U1 기록](history/U1-storage.md) · [U2 기록](history/U2-input-and-resize.md) · [U3 기록](history/U3-ttl.md) · [U4 기록](history/U4-cleanup.md) · [U5 기록](history/U5-concurrency.md)

## 목표

- 해시 충돌·확장·만료·동시 접근을 직접 구현하고 설명합니다.
- 외부 프로그램이 같은 저장소를 사용하고, API 응답 캐싱의 정확성과 성능을 검증합니다.
- 단위마다 기대 결과를 정하고 실제 실패·수정·검증 과정을 기록합니다.

**Python + Flask + Waitress / Windows**를 사용합니다. C의 수동 메모리 관리보다 저장소 동작과 검증에 집중하기 위한 선택이며, 구현 시간 단축이나 성능 우위를 측정한 결과는 아닙니다. 실제 Redis 전체 기능과 RESP 클라이언트 호환은 목표가 아닙니다.

## 폴더 구조

```text
main-redis/
├─ mini_redis/             실제 저장소 구현
│  ├─ __init__.py          패키지 선언, 서버·스레드 시작 없음
│  ├─ store.py             해시·노드·저장소·TTL·제한된 청소
│  └─ expiration.py        명시적으로 시작·종료하는 청소 스레드
├─ tests/
│  ├─ test_store.py        기본 저장소·입력·확장 테스트
│  ├─ test_ttl.py          시간 주입을 사용한 TTL 테스트
│  ├─ test_cleanup.py      청소·커서·갱신 겹침·생명주기 테스트
│  ├─ test_concurrency.py  여러 스레드의 요청·락·일관성 검사
│  ├─ test_cleanup_focus.py  필수 흐름 하나를 집중 검증
│  └─ load_cleanup.py      명시적으로 실행하는 청소 부하 실험
├─ docs/                  요구사항·설계·API·검증 계획
├─ history/               단위별 실행·실패·수정·재검증 기록
├─ study/                 개념 학습 노트
├─ AGENTS.md              AI 작업 규칙과 읽는 순서
└─ WORKLOG.md             현재 상태와 다음 작업
```

구현은 `mini_redis/`, 자동 검사는 `tests/`, 과정 설명은 `history/`에 둡니다. 테스트 파일은 기능·검증 목적에 맞춰 나누며 구현 단위마다 반드시 하나씩 만들지는 않습니다. Flask·데모 코드는 해당 단위에 들어갈 때 필요한 만큼 추가합니다.

## 프로젝트 문서

| 읽을 목적 | 문서 |
| --- | --- |
| AI가 이어서 작업하기 | [AGENTS.md](AGENTS.md) → [현재 작업 인계](WORKLOG.md) |
| 전체 문서의 역할·읽는 순서 | [docs/README.md](docs/README.md) |
| 과제와 프로젝트 범위 | [과제](docs/assignment.md) · [프로젝트 개요](docs/PROJECT.md) |
| 기대 동작과 통과 조건 | [REQUIREMENTS.md](docs/REQUIREMENTS.md) |
| 구조와 상태 소유 | [DESIGN.md](docs/DESIGN.md) |
| 선택 이유·대안·한계 | [DECISIONS.md](docs/DECISIONS.md) |
| HTTP 요청·응답 | [API.md](docs/API.md) |
| 구현 단위와 필수 테스트 | [TESTING.md](docs/TESTING.md) |
| 단위별 구현·테스트 이력 | [history/README.md](history/README.md) |
| 함께 검토·기록하는 방법 | [WORKFLOW.md](docs/WORKFLOW.md) |

## 합의한 전체 설계 — 일부는 아직 미구현

- FNV-1a 64비트, 연결 리스트 체이닝, 초기 16버킷. 신규 키로 적재율 0.75 초과 시 2배 전체 리해싱.
- 단일 프로세스·저장소 하나·공용 락 하나. 요청 워커 4개와 청소 스레드 1개가 공유합니다.
- UTF-8 문자열 키 최대 1 KiB, 값 최대 1 MiB. 빈 문자열과 원문 공백을 허용합니다.
- TTL은 양의 정수 밀리초, 단조 시간으로 판단합니다. 접근 검사와 목표 100ms 주기의 제한된 청소를 함께 사용합니다.
- POST /set, /get, /delete. 키는 JSON 본문에 전달합니다. 기본 주소 127.0.0.1:8080, 본문 최대 8 MiB.
- 영속성은 첫 범위에서 제외합니다. 서버 종료 시 데이터가 사라집니다.

숫자는 합의한 초기 설정입니다. 최적값이나 모든 만료 키의 100ms 내 회수를 보장하지 않습니다. HTTP 서버가 구현된 뒤 확인한 설치·시작 명령과 사용 예시를 추가합니다. 현재는 저장소 단위 테스트만 실행할 수 있습니다.

```powershell
python -m unittest discover -s tests -v
```

Python 3.13.14에서 확인했습니다. 현재 U1~U5 테스트는 표준 라이브러리만 사용하며 추가 설치가 필요하지 않습니다. 테스트는 실행한 경로의 증거이고 전체 저장소의 완성을 뜻하지 않습니다.

테스트별 역할과 선택 실행·부하 명령은 [tests/README.md](tests/README.md)를 확인하세요.

## 학습 문서

[학습 목차](study/00-overview.md)에서 Redis의 필요성 → 키·값과 캐시 → 해시 테이블 → TTL → 서버·동시성 → 메모리·영속성 → 선택 기록 → 검증 순서로 읽을 수 있습니다. 개념 설명과 제품 계약을 구분합니다.

## 저장소 안내

[팀 저장소](https://github.com/WEEK11-12/mini-redis)의 개인 포크이며 실제 프로젝트의 기준 브랜치는 main입니다. 학습 필기도 같은 main의 study/ 폴더에서 함께 관리합니다. 기존 study-jye 브랜치는 과거 기록으로 보존합니다. 두 사람 모두 Redis와 DBMS 전 과정을 경험하되 DBMS는 별도 프로젝트로 관리합니다. 개인 포크 변경이 팀 저장소에 자동으로 반영되지는 않습니다.
