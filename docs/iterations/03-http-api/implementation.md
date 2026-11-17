# 3단계 구현 기록 — HTTP 연결과 응답 재사용

- 상태: 구현 및 3단계 범위 독립 승인 — 최신 HTTP·저장소 공식 테스트 통과
- 근거: [요구사항](requirements.md), [설계](design.md), [TC 목록](test-cases.md), [검증 기록](verification.md)

## 변경 경로와 흐름

- `mini_redis/http_api.py`: 단일 스레드 `HTTPServer`와 기존 `HashTableStore` 공개 연산을 연결한다. 원시 경로에서 키·라우트·메서드·쿼리를 순서대로 분류하고 PUT의 단일 `Content-Length`·정확한 미디어 유형·64 KiB 상한·UTF-8 JSON 문자열 필드를 확인한 뒤에만 저장소를 호출한다. 선언 길이 초과는 본문을 읽기 전에 거부한다. 최종 응답에는 `no-store`를 적용하고, 읽기 부족·본문 거부 뒤 연결을 닫는다. 본문 읽기 소켓 타임아웃은 2초다.
- `examples/origin_api.py`: 별도 프로세스의 고정 데이터 API와 데이터 요청 횟수를 소유한다. `/origin-calls` 조회는 횟수를 늘리지 않는다.
- `examples/client.py`: 프로세스마다 캐시 조회를 시작한다. `404 KEY_NOT_FOUND`일 때만 원본을 조회하고 성공한 PUT 뒤 값을 출력한다. 다른 실패는 오류로 종료하며 자체 캐시는 없다.
- `mini_redis/store.py`는 수정하지 않았다. 저장소 버킷은 HTTP 계층에서 접근하지 않는다.

독립 검토의 3개 수정 요청에 따라 `mini_redis/http_api.py`는 긴 선행 0 길이를 짧은 유효 숫자로 한 번 변환하고, `examples/client.py`는 리다이렉트를 따라가지 않고 PUT의 `stored`가 실제 JSON 불리언 `true`인지 확인한다. `tests/test_http_api.py`에 이 세 경계의 회귀 테스트를 추가했다. 저장소 코드는 수정하지 않았다.

설계의 네 연산과 실패 분류를 그대로 적용했다. HTTP 응답 후 연결을 닫는 방식으로 읽지 않은 요청 본문을 다음 요청으로 해석하지 않는다. 서버 상태는 프로세스 메모리에만 남고 TTL·동시성·영속성은 구현하지 않았다.

## 실행 방법

저장소 루트에서 Python 3으로 각 명령을 별도 터미널에서 실행한다.

```sh
python3 -m mini_redis.http_api --host 127.0.0.1 --port 8000
python3 -m examples.origin_api --host 127.0.0.1 --port 8001
python3 -m examples.client --cache-url http://127.0.0.1:8000 --origin-url http://127.0.0.1:8001
```

서버 준비 확인은 원본의 `GET http://127.0.0.1:8001/origin-calls`와 저장소의 `GET http://127.0.0.1:8000/keys/example-demo`로 할 수 있다. 클라이언트를 두 번 실행하고 원본 횟수 `0 → 1 → 1`을 확인한다. 두 서버를 각각 `Ctrl-C`로 종료하고 재시작하면 상태가 초기화된다. 포트 충돌로 기동 실패하면 다른 포트를 두 서버와 클라이언트에 동일하게 지정한다. 실제 테스트 실행·결과는 [검증 기록](verification.md)에 구분해 남긴다.
