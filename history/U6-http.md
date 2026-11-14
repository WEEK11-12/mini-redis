# U6 — Flask·Waitress HTTP 연결

## 목적과 사용자 합의

R-08·R-09·R-10, T-12·T-14·T-15를 검증한다. 사용자가 정상 연결, 입력 오류와 상태 보존, 실제 Waitress 통신, 서버·청소 생명주기의 네 묶음과 오류 규칙에 동의했다.

중복 JSON 필드·잘못된 UTF-8는 400, 크기 초과 413, 콘텐츠 형식 오류 415다. Flask의 404·405·500도 공통 JSON이며 500에 내부 예외를 노출하지 않는다. 오류가 겹치면 먼저 발견한 하나를 반환한다. Waitress 선행 거부 응답은 별도로 확인한다.

## 구현과 선택 이유

- mini_redis/api.py: 앱 생성 함수가 전달받은 저장소 하나를 모든 경로에서 공유한다. `store or MiniRedisStore()`를 쓰면 빈 저장소가 거짓으로 평가되므로, 저장소는 필수 인자로 명시했다.
- 입력은 콘텐츠 형식 → 본문 제한·UTF-8/JSON → 객체·필드 → 문자열·길이 → TTL 순서로 검사한다. 전체 검증 후에만 저장소를 호출한다. 저장소의 독립 입력 검사는 유지한다.
- 표준 json 파서의 object_pairs_hook으로 중복 필드를 거부한다. 기본 파서의 마지막 값 선택으로 입력 실수를 숨기지 않는다. NaN·Infinity 등 JSON 밖 상수도 거부한다.
- HTTP 오류의 원래 응답을 사용하면서 본문만 JSON으로 교체해 405의 Allow 헤더를 보존한다. 예기치 않은 예외는 Flask가 로그에 남기고, 사용자에게는 일반적인 500 메시지만 반환한다.
- mini_redis/server.py: 저장소 하나 생성 → 청소 시작 → Waitress 실행 → finally에서 청소 stop/join. 요청마다 청소를 만들지 않는다. import와 앱 생성은 서버를 시작하지 않는다.
- requirements.txt에는 합의한 Flask 3.1.3·Waitress 3.0.2만 직접 의존성으로 고정했다. 하위 의존성은 패키지 관리자가 설치하며 완전한 환경 잠금 파일은 아니다.

## 실제 실패·문제·수정

1. 환경: `python -m venv .venv`가 ensurepip 실패로 종료했다. 상세 실행에서 Windows 임시 폴더의 PermissionError를 확인했다. 같은 가상환경 생성을 승인된 권한으로 재실행해 성공했고 합의한 두 패키지를 .venv에 설치했다. 제품 버그가 아니다.
2. 미구현: API 테스트 최초 실행은 `ModuleNotFoundError: mini_redis.api`로 실패했다. 구현 후 7개 PASS. 서버 테스트 최초 실행도 server 모듈 부재로 실패했고 구현 후 3개 PASS. 기존 저장소의 실패로 기록하지 않는다.
3. 경계 검토: 설치한 Waitress parser.py는 본문이 설정값 이상이면 거부한다. Flask는 설정값 초과를 거부한다. 정확히 8 MiB를 허용하기 위해 Waitress 설정만 8 MiB + 1바이트로 맞췄다. 이 차이는 소스 검토에서 발견했으며 수정 전 실패를 실행했다고 주장하지 않는다. 수정 후 실제 통신에서 정확한 경계를 검증했다.

## 환경·명령·실제 결과

Windows, Python 3.13.14, Flask 3.1.3, Waitress 3.0.2. main-redis 루트에서 실행했다.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_api -v
.\.venv\Scripts\python.exe -m unittest tests.test_server -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

| 검사 | 입력과 확인한 결과 | 판정 |
| --- | --- | --- |
| Flask 정상·TTL | 빈 문자열·공백·한글·줄바꿈·이모지 원문 유지, 저장/조회/삭제, 주입 시간 1ms 직전·같음, 만료 삭제 false, TTL 없는 덮어쓰기 | PASS |
| 입력 거부와 보존 | 필수 누락·미정의 필드·잘못된 타입·TTL, 중복 필드·깨진 JSON·배열/null·NaN·고립 surrogate·잘못된 UTF-8 바이트 | PASS |
| 문자열 제한 | 2바이트 문자로 키 1,024·값 1,048,576바이트 허용, 1바이트 초과 413·기존 값 유지 | PASS |
| Flask 오류 | 본문 정확히 8 MiB 허용·초과 413, 비JSON 415, 404/405/500 JSON, Allow 보존·500 내부 정보 비노출 | PASS |
| 실제 Waitress | OS가 배정한 localhost 포트, 요청 워커 4개·클라이언트 4개로 서로 다른 키 저장 후 별도 요청으로 조회·삭제 | PASS |
| 실제 본문 제한 | 8,388,608바이트 JSON+공백 본문은 200. Content-Length 8,388,609는 본문 전송 전에 413, Content-Type text/plain, 본문에 exceeds max_body 확인. 이후 정상 요청도 200 | PASS |
| 생명주기 | import 시 serve/Thread.start 호출 없음. 실제 청소 작업자 하나가 서버 실행 중 동작하고 KeyboardInterrupt 경로 및 시작 OSError 뒤 종료 | PASS |

API 7개·서버 3개, 마지막 회귀 실행은 기존 44개 포함 **54개 PASS**. 실제 소켓은 테스트에서 명시 종료하고 서버 스레드 join을 확인했다. 10,000키 부하는 다시 실행하지 않았다.

## 주요 코드 읽기와 남은 경계

`set_value`는 검증된 JSON을 `store.set(**data)`로 전달한다. ttl_ms를 생략하면 키 자체를 넘기지 않으므로 저장소의 기존 생략 규칙이 유지된다. `get_value`의 `value is not None`은 빈 문자열도 찾은 값으로 처리한다.

`server.main`의 finally는 서버 오류에도 청소 종료를 시도한다. 테스트는 실제 Waitress 서버를 별도 스레드에서 실행하고 명시 정리했으며, 진입점의 인터럽트는 주입했다. Windows 터미널에서 실제 Ctrl+C 키 입력이나 프로세스 강제 종료를 검증한 것은 아니다. 강제 종료에서는 finally를 보장하지 않는다.

HTTP 동시 요청의 동시 실행 순서나 모든 워커 배정을 보장하지 않는다. U5의 저장소 락 검증과 함께 해석한다. 본문 제한은 저장소 전체 메모리·요청 대기열 제한이 아니다. 파서는 Python 기본 정수 자릿수·중첩 깊이 한계를 따르므로 TTL 의미상의 기간 상한 없음과 파서 자원 제한은 구분한다.

상태: 로컬 구현·필수 검증 완료, 사용자 핵심 코드 확인 대기. 커밋·푸시 및 U7 구현은 하지 않았다.

참고: [Flask API](https://flask.palletsprojects.com/en/stable/api/), [Waitress 설정](https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html), [Waitress 실행과 종료](https://docs.pylonsproject.org/projects/waitress/en/stable/usage.html). 본문 비교 연산은 설치한 3.0.2의 parser.py도 직접 확인했다.
