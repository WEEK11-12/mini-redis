# HTTP API 규격

상태: 사용자 합의 완료, 서버 미구현·요청 예시 미실행. JSON 본문으로 키를 전달한다. 빈 키·공백·슬래시·줄바꿈을 URL 경로에 넣지 않고 같은 형태로 표현하기 위한 선택이다. RESP나 redis-cli와 호환되지 않는다.

## 요청과 성공 응답

모두 POST, Content-Type: application/json. 응답도 JSON이다.

| 경로 | 허용 필드 | 필수 필드 | HTTP 200 응답 |
| --- | --- | --- | --- |
| /set | key, value, ttl_ms | key, value | {"ok":true} |
| /get | key | key | {"found":true,"value":"값"} 또는 {"found":false,"value":null} |
| /delete | key | key | {"deleted":true} 또는 {"deleted":false} |

```json
{"key":"name","value":"지예","ttl_ms":1500}
```

/set의 ttl_ms 생략은 무기한 저장이며 기존 TTL을 지운다. null은 생략이 아니다. 정상 TTL은 양의 정수 밀리초다. 없는 키 조회·삭제는 정상 결과로 200을 사용한다. 만료 키 조회도 found:false다. 이미 만료된 키는 노드가 남았어도 deleted:false이며 그 노드는 함께 정리한다. TTL에 별도 기간 상한은 없지만 요청 본문과 파서의 자원 제한은 별개다.

## 입력 검사

- JSON 객체만 받는다. 깨진 JSON, 배열·숫자·null 등 객체가 아닌 본문은 400.
- 필수 필드 누락, 정의하지 않은 필드, 문자열이 아닌 key/value는 400.
- ttl_ms의 null·0·음수·소수·문자열·bool은 400. /get이나 /delete의 ttl_ms도 미정의 필드다.
- 빈 키·값 허용, 공백 제거·자동 형 변환 없음. UTF-8 키 최대 1 KiB, 값 최대 1 MiB.
- 수신 본문은 최대 8 MiB. JSON 이스케이프 표현 때문에 해석 후 문자열보다 본문이 커질 수 있다.
- ttl이라는 오타를 무시하고 무기한 저장하지 않는다. 요청 전체 검증을 통과해야 변경한다.

## 오류

| 상황 | 상태 코드 | 응답 |
| --- | --- | --- |
| 입력 규칙 위반·잘못된 JSON | 400 | 아래 공통 JSON 형식 |
| 키·값·본문 크기 초과 | 413 | 공통 JSON 형식 |
| JSON이 아닌 콘텐츠 형식 | 415 | 공통 JSON 형식 |

```json
{"error":{"code":"INVALID_INPUT","message":"잘못된 입력에 대한 설명"}}
```

INVALID_INPUT은 입력 오류 예시로 합의했다. 크기·콘텐츠 형식 등의 구체 code 목록, 여러 오류가 겹칠 때 우선순위, 404/405/500 형식은 HTTP 단위에서 테스트 전에 정한다. 서버가 Flask 실행 전에 거부한 요청의 오류 본문도 별도로 확인한다. 임의로 모든 네트워크 오류가 JSON이라고 보장하지 않는다.

## 사용하는 방식과 한계

조회도 POST인 명령형 API다. GET 본문에 의존하지 않고 빈 키와 특수문자를 일관되게 전달한다. URL 기반 GET처럼 일반 HTTP 캐시가 자동 활용되는 API를 목표로 하지 않는다.

기본 접속 주소는 http://127.0.0.1:8080 이다. 실행 가능한 HTTP 서버는 아직 없으므로 설치·실행 명령을 검증한 것처럼 제시하지 않는다. [설계](DESIGN.md) · [테스트](TESTING.md)
