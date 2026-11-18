# 테스트 실행 안내

실제 구현은 ../mini_redis/, 자동 검사는 이 폴더, 실행 과정과 결과는 [history](../history/README.md)에 둔다. 기대 동작·요구 ID·미구현 범위는 [TESTING](../docs/TESTING.md)이 기준이다.

## 파일과 역할

| 파일 | 대상 | 자동 테스트 수 |
| --- | --- | --- |
| [test_store.py](test_store.py) | U1 저장·조회·삭제·충돌, U2 입력·해시·확장 | 16 |
| [test_ttl.py](test_ttl.py) | U3 TTL, FakeClock 시간 도우미 | 10 |
| [test_cleanup.py](test_cleanup.py) | U4 청소·커서·갱신 겹침·작업자 시작/종료 | 15 |
| [test_cleanup_focus.py](test_cleanup_focus.py) | 중간 만료 삭제·연결·이어가기 집중 확인 | 1 |
| [test_concurrency.py](test_concurrency.py) | U5 요청 대기·자료 보존·확장 | 2 |
| [test_api.py](test_api.py) | U6 정상 HTTP·TTL·입력 거부·오류와 보존 | 7 |
| [test_server.py](test_server.py) | U6 실제 Waitress 통신·본문 제한·시작/종료 | 3 |
| [test_cache_demo.py](test_cache_demo.py) | U7 실제 HTTP 미사용·Miss·Hit·만료·삭제·화면·의존 오류 | 3 |
| [measure_cache.py](measure_cache.py) | U7 20회씩 순차 HTTP 시간·원본 호출 비교 | 자동 검색 제외 |
| [load_cleanup.py](load_cleanup.py) | 실제 작업자의 10,000키 청소 부하 | 자동 검색 제외 |

__init__.py는 모듈 방식의 실행을 지원한다. 테스트가 구현을 호출하며 제품 코드는 테스트를 import하지 않는다. HTTP 검사는 test_api.py·test_server.py이며 캐시 검사는 test_cache_demo.py에서 원본·예제·Redis의 실제 HTTP 통신으로 확인한다.

## 실행 위치와 명령

main-redis 루트에서 Python 3.13.14로 확인했다. U6 검사는 프로젝트 .venv에 requirements.txt를 설치한 뒤 실행한다. 서버 검사는 임시 localhost 포트를 열고 종료한다.

```powershell
# 현재 자동 테스트 전체: 57개
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# U6 필수 범위
.\.venv\Scripts\python.exe -m unittest tests.test_api tests.test_server -v

# U7 필수 동작
.\.venv\Scripts\python.exe -m unittest tests.test_cache_demo -v

# 필수 사례를 골라 실행하는 예
.\.venv\Scripts\python.exe -m unittest tests.test_cleanup_focus -v
.\.venv\Scripts\python.exe -m unittest tests.test_concurrency -v
```

단위 작업 중에는 합의한 필수 범위를 선택한다. 전체 명령은 커밋 전이나 여러 기능의 회귀 위험을 확인할 때 사용하며 매번 반복할 필요는 없다. 실패가 나오면 더 많은 실행으로 덮지 말고 해당 입력·원인을 먼저 확인한다.

## 캐시 시간 비교는 별도 실행

```powershell
.\.venv\Scripts\python.exe -m tests.measure_cache
```

로컬 Waitress 서버 세 개를 임시 포트에 시작하고 종료합니다. 원본 50ms 대기, 측정용 TTL 60초, 미사용·Miss·Hit 각 20회 순차 요청입니다. 원본 횟수·데이터·경로를 필수 확인하며 시간 배속 기준은 없습니다. 실행하면 history/U7-cache-result.json을 갱신하므로 이력·README의 측정값도 함께 확인합니다. [U7 조건과 한계](../history/U7-cache.md)

## 부하는 별도 실행

```powershell
.\.venv\Scripts\python.exe -m tests.load_cleanup
```

약 10,000키를 사용하는 명시적 실험이다. 실제 작업자 대기 때문에 수십 초가 걸릴 수 있다. [부하 결과 JSON](../history/U4-cleanup-load-result.json)을 새 실행 결과로 갱신하므로, 재실행하면 문서의 측정값·판정과 Git 변경도 함께 확인한다. 일반 자동 테스트나 HTTP 성능 측정과 구분한다.
