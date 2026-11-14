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
| [load_cleanup.py](load_cleanup.py) | 실제 작업자의 10,000키 청소 부하 | 자동 검색 제외 |

__init__.py는 모듈 방식의 실행을 지원한다. 테스트가 구현을 호출하며 제품 코드는 테스트를 import하지 않는다. HTTP·캐시 테스트 파일은 아직 없다.

## 실행 위치와 명령

main-redis 루트에서 Python 3.13.14로 확인했다. 현재 테스트는 표준 라이브러리만 사용한다.

```powershell
# 현재 자동 테스트 전체: 44개
python -m unittest discover -s tests -v

# 필수 사례를 골라 실행하는 예
python -m unittest tests.test_cleanup_focus -v
python -m unittest tests.test_concurrency -v
```

단위 작업 중에는 합의한 필수 범위를 선택한다. 전체 명령은 커밋 전이나 여러 기능의 회귀 위험을 확인할 때 사용하며 매번 반복할 필요는 없다. 실패가 나오면 더 많은 실행으로 덮지 말고 해당 입력·원인을 먼저 확인한다.

## 부하는 별도 실행

```powershell
python -m tests.load_cleanup
```

약 10,000키를 사용하는 명시적 실험이다. 실제 작업자 대기 때문에 수십 초가 걸릴 수 있다. [부하 결과 JSON](../history/U4-cleanup-load-result.json)을 새 실행 결과로 갱신하므로, 재실행하면 문서의 측정값·판정과 Git 변경도 함께 확인한다. 일반 자동 테스트나 HTTP 성능 측정과 구분한다.
