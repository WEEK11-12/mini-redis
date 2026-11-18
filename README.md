# Mini Redis

직접 구현한 **해시 테이블**을 저장소로 삼아, 여러 클라이언트가 **HTTP API**로 저장·조회·존재 확인·삭제를 할 수 있는 가벼운 인메모리 키-값 캐시입니다. 만료 시간(TTL)과 명시적 삭제(무효화), 외부 API 응답 재사용 사례, 동시 요청 처리 구조, 캐시 사용 전후의 성능 비교까지 다룹니다.

## 한눈에 보기

```text
외부 클라이언트 ──HTTP──▶ 요청 접수·검증 ──▶ 명령 큐 ──▶ 명령 실행 스레드 1개 ──▶ HashTableStore
 (examples/client.py)   (mini_redis/http_api.py)                                (mini_redis/store.py)
                                                         └ 만료 항목 정리도 같은 스레드에서 수행
```

- **저장소:** 해시값을 버킷 수로 나눈 나머지로 버킷을 고르고, 같은 버킷의 충돌 키는 전체 키를 비교해 구분합니다. 적재율이 1을 넘으면 버킷을 두 배로 늘려 재해싱합니다.
- **만료·무효화:** TTL은 별도 요청으로 설정·갱신·제거하고, 일반 저장(PUT)은 이전 TTL을 해제하며, `DELETE`가 명시적 무효화입니다. 만료된 키는 없는 키처럼 응답합니다.
- **동시성:** HTTP 요청의 접수·해석은 병렬로 하되, 저장소를 읽거나 바꾸는 모든 명령(만료 정리 포함)은 한 스레드가 차례로 처리해 경쟁 상태를 피합니다.
- **활용 사례:** 별도 프로세스의 원본 API 응답을 캐시 미스일 때만 가져와 저장하고, 다음 호출부터는 캐시에서 재사용합니다.

## AI와 함께 만든 과정

이 프로젝트는 **개발자가 범위와 선택을 판단하고, 에이전트가 역할별로 초안·설계·구현·검증을 지원하는 반복 루프**로 진행했습니다. 설계를 먼저 모두 끝내지 않고, **단계마다 요구사항→설계→설계 검증→구현 전 TC→구현→구현 검증의 한 사이클을 돌려** 앞 단계의 결과를 다음 단계에 반영했습니다. 설계와 구현은 작성한 에이전트가 아니라 별도의 검증 에이전트가 검토했고, 수정 요청이 나오면 해당 단계로 돌아갔습니다. 단계 간 계약이 바뀌면 새 결정으로 기록했습니다(3단계의 순차 서버 → 5단계의 단일 명령 스레드, [D-0007](docs/decisions/0007-single-thread-command-execution.md)).

```text
1단계: 범위·공유 계약만 정함
  └─ 2~5단계, 단계마다:  요구사항 → 설계 → 설계 검증 → 구현 전 TC → 구현 → 구현 검증 → 범위 승인
                                      ▲ 수정 요청 ┘                    ▲ 수정 요청 ┘
  └─ 6단계: 새 요구사항 없이 전체 사용 흐름·성능 검증, 개발자의 결과 확인·설명
```

- 3~5단계에서는 독립 검증이 캐시 리다이렉트 허용, 만료 제거 중 항목 수 불일치, 완료 통지 실패 시 영구 대기 같은 결함을 실제로 찾았고, 수정과 회귀 테스트·재검토를 거쳐 승인했습니다. ([검증 루프가 잡아낸 것](docs/iterations/README.md#검증-루프가-실제로-잡아낸-것))
- 에이전트의 완료 보고만으로 승인하지 않고 소스 해시와 실행 결과를 대조했으며, 승인 범위를 검토한 범위로 한정했습니다. ([검증 방식](docs/iterations/README.md#검증을-믿을-수-있게-한-방식))
- 사람이 정한 측정 조건과 직접 설명한 핵심 로직은 [사람의 개입 지점](docs/iterations/README.md#사람의-개입이-결과를-바꾼-지점)에 구분해 적었습니다.
- 반복 방식, 역할·모델 표, 단계별 사례: [AI와 함께 진행한 반복 루프](docs/iterations/README.md#ai와-함께-진행한-반복-루프) · 진행 원칙: [D-0001](docs/decisions/0001-project-workflow.md)

## 폴더 구조와 의미

```text
mini-redis/
├── README.md                  이 문서: 프로젝트 입구
├── mini_redis/                제품 코드
│   ├── store.py                 해시 테이블 저장소 (직접 구현, 만료 기한·정리 포함)
│   └── http_api.py              HTTP API, 입력 검증, 명령 큐와 단일 실행 스레드
├── examples/                  활용 사례와 측정 도구
│   ├── origin_api.py            SQLite 파일 DB에서 조회해 응답하는 가상의 원본 API
│   ├── seed_db.py               원본 API용 SQLite DB 생성(기본 1만 행)
│   ├── client.py                캐시 조회 → 미스일 때만 원본 호출·저장하는 클라이언트
│   └── benchmark.py             캐시 미사용·미스·히트 지연시간 측정
├── tests/                     자동화 테스트 (저장소·HTTP·만료·동시성)
└── docs/                      사람이 읽는 모든 문서
    ├── assignment.md            과제 원문 (기준)
    ├── requirements.md          요구사항 통합 안내: 단계별 요구사항을 한 곳에서 요약
    ├── design.md                설계 통합 안내: 구조와 주요 선택을 한 곳에서 요약
    ├── implementation.md        구현 통합 안내: 코드 경로·역할·실행 방법 요약
    ├── decisions/               주요 결정 기록 D-0001~0007 (선택 이유·영향·재검토 조건)
    ├── iterations/              1~6단계 작업 기록 (아래 설명)
    ├── conventions.md           문서·결정·코드 운영 규칙
    └── study/                   Redis 개념 학습 자료
```

`docs/iterations/`는 작업을 6개 단계로 나눠 진행한 기록입니다. 각 단계 폴더에는 보통 `overview.md`(입구·체크리스트), `requirements.md`(요구사항과 인수 조건), `design.md`(설계), `test-cases.md`(구현 전 테스트 계획), `implementation.md`(구현 기록), `verification.md`(실제 실행 결과)가 있습니다. 상위의 `README.md`는 단계별 진행 결과, `implementation-units.md`는 착수 당시의 작업 순서 제안, `iteration-deliverables.md`는 파일별 작성 기준입니다. 1단계는 코드 없는 계약 단계, 6단계는 기존 요구를 검증하는 단계라 일부 파일이 없습니다.

| 단계 | 내용 |
| --- | --- |
| 1 | [범위·공유 계약](docs/iterations/01-scope-and-contract/overview.md) |
| 2 | [해시 테이블 저장소](docs/iterations/02-hash-table/overview.md) |
| 3 | [HTTP API·응답 재사용](docs/iterations/03-http-api/overview.md) |
| 4 | [만료·무효화](docs/iterations/04-expiration-invalidation/overview.md) |
| 5 | [동시성](docs/iterations/05-concurrency/overview.md) |
| 6 | [전체 사용·성능 검증](docs/iterations/06-integration-performance/overview.md) |

에이전트 전용 `AGENTS.md`와 `.agent/`는 Git에서 제외된 로컬 파일입니다.

## 주제별로 읽기

| 궁금한 주제 | 먼저 볼 문서 | 근거 상세 |
| --- | --- | --- |
| 무엇을 왜 만들었나 | [과제 원문](docs/assignment.md), [D-0002 Python·HTTP 선택 이유](docs/decisions/0002-python-http-interface.md), [요구사항 통합 안내](docs/requirements.md) | [1단계 범위·계약](docs/iterations/01-scope-and-contract/overview.md) |
| 해시 테이블 구현과 설명 (핵심 로직) | [설계 통합 안내](docs/design.md) | [2단계 설계](docs/iterations/02-hash-table/design.md), [2단계 구현](docs/iterations/02-hash-table/implementation.md), 코드 `mini_redis/store.py` |
| 외부에서 쓰는 방법과 API 응답 재사용 | [3단계 설계 4절](docs/iterations/03-http-api/design.md#4-외부-사용-예제의-흐름과-실패), [D-0003 기본 HTTP 계약](docs/decisions/0003-http-response-contract.md) | [3단계 실행 방법](docs/iterations/03-http-api/implementation.md#실행-방법) |
| 만료와 무효화를 어떻게 처리했나 | [D-0006 TTL·무효화 계약](docs/decisions/0006-ttl-invalidation-contract.md) | [4단계 설계](docs/iterations/04-expiration-invalidation/design.md), [4단계 검증](docs/iterations/04-expiration-invalidation/verification.md) |
| 동시성 문제를 어떻게 다뤘나 | [D-0007 단일 명령 실행 스레드](docs/decisions/0007-single-thread-command-execution.md) | [5단계 설계](docs/iterations/05-concurrency/design.md), [5단계 검증](docs/iterations/05-concurrency/verification.md) |
| 캐시를 쓰면 빨라졌나 (성능 비교) | [6단계 개요의 측정 조건](docs/iterations/06-integration-performance/overview.md#확정된-성능-비교-조건) | [6단계 성능 결과·해석](docs/iterations/06-integration-performance/verification.md#3-성능-비교-실행) |
| AI와 어떻게 진행·검증했나 | [AI와 함께 진행한 반복 루프](docs/iterations/README.md#ai와-함께-진행한-반복-루프), [D-0001 진행 방식](docs/decisions/0001-project-workflow.md) | [검증 루프가 잡아낸 것](docs/iterations/README.md#검증-루프가-실제로-잡아낸-것), [산출물 가이드](docs/iterations/iteration-deliverables.md) |

**성능 비교 결과 읽는 법:** 원본이 고정 응답을 돌려주던 처음 조건에서는 캐시 히트(중앙값 약 0.38ms)가 캐시 미사용(약 0.23ms)보다 느렸습니다. 과제 의도(서버 DB 조회 대 메모리 캐시 읽기)에 맞춰 원본을 SQLite 파일 DB 조회로 바꿔 다시 측정했지만, 같은 실행 안에서 여전히 히트(약 0.51ms)가 미사용(약 0.40ms)보다 느렸습니다(이 재측정은 독립 검증 대기). 같은 키 하나를 반복 조회해 DB 작업이 캐시된 페이지에서 끝나고, 두 경로 모두 로컬 HTTP 왕복이 대부분이며 히트에는 요청 해석·명령 스레드 경유가 더해지기 때문으로 *추정*합니다(구간별 시간은 측정하지 않음). DB 조회가 디스크 접근이라고 단정하지 않으며, 캐시가 빠르다고도 느리다고도 일반화하지 않습니다. ([측정 방법·한계](docs/iterations/06-integration-performance/verification.md#3-성능-비교-실행))

## 실행과 확인

저장소 루트에서 Python 3으로 실행합니다.

```sh
python3 -m unittest discover -s tests -p 'test_store.py' -q
python3 -m unittest discover -s tests -p 'test_http_api.py' -q
python3 -m unittest discover -s tests -p 'test_expiration_store.py' -q
python3 -m unittest discover -s tests -p 'test_expiration_http.py' -q
```

Mini Redis·원본 API·클라이언트 실행 명령은 [3단계 구현 기록](docs/iterations/03-http-api/implementation.md#실행-방법), 성능 측정 명령은 [6단계 검증](docs/iterations/06-integration-performance/verification.md#3-성능-비교-실행)에 있습니다. `tests/test_concurrency_http.py`의 동시성 테스트는 임시 시험 접점을 계측해 실행했으며, 위 명령처럼 보정 없이 실행한 통과 결과로 보지 않습니다. 실제 실행 결과는 [5단계 검증](docs/iterations/05-concurrency/verification.md)에 있습니다.

## 완료 범위와 한계

1~6단계는 각각 합의한 범위에서 완료했습니다. 6단계는 외부 사용 흐름 7개 시나리오(E-001~007)를 모두 통과했고 성능 비교는 조건별 100회씩 성공했습니다. 다음은 완료 범위 밖이거나 구분해서 읽어야 합니다.

- 핵심 로직을 설명할 수 있는지는 본인 확인이며 독립 구술 검증이 아닙니다.
- 성능 결과는 한 대의 로컬 호스트, 고정 응답 또는 단일 키 SQLite 조회 원본, 순차 단일 클라이언트 기준입니다. 파일 DB 조회 조건의 재측정은 독립 검증 전입니다.
- 서버 중단 시 데이터 보존(영속성, 과제의 Optional 항목), 고정 포트 수동 시연, 배포는 포함하지 않았습니다.
- 여러 스레드가 저장소 객체를 직접 호출하는 경우의 안전성은 보장하지 않습니다. HTTP 경로를 통한 사용만 범위입니다.
