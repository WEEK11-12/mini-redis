# 5. Flask·Waitress와 동시 요청

저장소가 메모리에 있어도 외부에서 쓰려면 요청을 받는 입구가 필요하다. Flask는 URL에 맞는 함수를 실행하고 JSON 입력·응답을 다룬다. Waitress는 네트워크 요청을 받아 Flask를 실행하는 WSGI 서버다. WSGI는 Python 웹 앱과 실행 서버 사이의 연결 규격이다.

```text
외부 앱 → HTTP → Waitress → Flask 입력 검사
       → 저장소 락 획득 → 해시 테이블 작업 → 락 반환 → JSON 응답
```

## 요청 스레드와 저장소 락은 다른 역할

Waitress는 한 프로세스에서 정해진 요청 워커를 재사용한다. 초기 워커 4개는 저장 전용·조회 전용처럼 역할을 나누지 않는다. 비어 있는 워커가 다음 요청을 처리한다. 모두 바쁘면 대기한다.

Flask 개발 서버도 Windows에서 동작하고 스레드 처리를 지원한다. 불가능해서 제외한 것이 아니라, 개발·디버깅용 서버와 실제 실행·측정용 서버를 구분하려고 Waitress를 선택했다. 고정 풀도 느린 작업에 묶일 수 있으며 무조건 빠르지는 않다.

저장소에는 요청 4개와 별도 청소 1개가 접근할 수 있다. 같은 락으로 보호하므로 내부에서는 한 번에 하나만 처리한다. 락을 가지고 있어도 스레드 전환은 가능하지만 다른 작업은 같은 저장소 락에서 기다린다. 세마포어는 현재 추가하지 않는다. GIL도 여러 단계의 저장소 변경을 보호하는 공용 락을 대신하지 않는다.

여러 프로세스는 메모리 저장소를 자동 공유하지 않는다. 현재는 프로세스 하나만 실행한다. 별도 요청으로 0을 읽고 1을 쓰는 동작 전체까지 락이 트랜잭션으로 묶어주지는 않는다.

## HTTP와 TCP

Flask는 TCP·HTTP의 대체재가 아니다. HTTP/1.1은 보통 TCP 위에서 사용된다. 프레임워크·서버가 네트워크 처리의 상당 부분을 맡는 것이다. 예전에 검토한 자체 줄바꿈 TCP 명령은 폐기했다. 실제 Redis의 RESP 및 redis-cli와도 호환되지 않는다.

우리 API는 POST /set·/get·/delete다. 빈 키·공백·슬래시 등을 JSON으로 전달하기 위해 조회도 POST를 쓴다. 정확한 필드와 오류는 [API 규격](../docs/API.md)에 모은다.

## 시작과 종료

실행 진입점에서 저장소와 락을 만들고 청소 스레드를 하나 시작한 뒤 Waitress를 실행한다. import만으로 시작하지 않는다. 종료 시 finally에서 Event로 청소에 종료를 알리고 끝났는지 확인한다. 이때 저장소 락을 잡고 기다리지 않는다. 강제 종료에서는 정리 코드를 보장할 수 없다.

기본 접속은 같은 컴퓨터의 127.0.0.1:8080이다. 외부 프로그램 사용과 인터넷 공개는 같은 뜻이 아니다. 다른 컴퓨터에서 접속할 때는 주소와 노출 범위를 확인한다. 본문 제한은 서버와 Flask 양쪽에 설정하며, 실제 서버 오류가 API JSON 형식과 같은지는 연결 테스트로 확인한다.

[Flask 생명주기](https://flask.palletsprojects.com/en/stable/lifecycle/) · [개발 서버](https://flask.palletsprojects.com/en/stable/server/) · [Waitress](https://flask.palletsprojects.com/en/stable/deploying/waitress/) · [HTTP RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html)

[이전](04-expiration.md) · [목차](00-overview.md) · [다음](06-memory-and-persistence.md)
