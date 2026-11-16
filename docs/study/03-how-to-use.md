[⬅ overview](./00-overview.md)

---

# 3. 사용자가 실제로 쓰는 기능 (구현 범위 정하기)

> - 기본 명령: SET, GET, DEL, EXISTS
> - 만료 시간(TTL): EX, EXPIRE, TTL
> - 자료구조와 편의: String, List, Hash, Set, Sorted Set
> - 원자적 명령: INCR 등 "읽고-계산하고-쓰기"를 한 번에
> - 접속 방식: redis-cli, 언어별 클라이언트 라이브러리

---

## 기본 명령
- 저장 : **SET** `user:1:name` "민지"
- 조회 : **GET** `user:1:name` → "민지" / 값 없음
- 존재 : **EXISTS** `user:1:name` → 1 (키가 있음) / 0 (키가 없음)
- 삭제 : **DEL** `user:1:name`
> 참고 : key인 `user:1:name`은 하나의 문자열일 뿐, 기능적인 의미가 있는 것은 아니다.

#### TTL
- 만료시간 → 키가 자동으로 사라지게 함
- `EX` : 키-값 저장 시에 만료 시간을 함께 정함
  ``` plain text
  SET login:code "4821" EX 60
  ```
- `EXPIRE` : 이미 저장된 키에 만료 시간을 붙임
  ``` plain text
  SET login:code "4821"
  EXPIRE login:code 60
  ```
- `TTL` : 키가 만료되기까지 남은 시간을 확인하는 명령
  ``` plain text
  SET login:code "4821" EX 60
  TTL login:code
  ```
  - 남은 시간을 초 단위로 반환해줌.
  - 결과가 -1 : 키는 있지만, 만료 시간이 설정되지 않은 것
  - 결과가 -2 : 키가 없는 것 (만료 시간 지나 유효하지 않은 경우 포함)

---

## 자료구조와 편의
#### String
- `String` : 키 하나에 값 하나를 저장
- 숫자 67을 저장하는 경우
  - Redis에서는 String으로 인식
  - `SET score 67` → `GET score` 결과 "67"
  - String 값이 정수로 해석되는 경우도 많음 → `INCR`처럼 숫자를 다루는 명령 호출 가능
#### List
- `List` : 키 하나에 순서가 있는 값 여러 개를 저장
  ``` plain text
  RPUSH recent:pages "home" "search" "product"
  LRANGE recent:pages 0 -1  → ["home", "search", "product"]
  ```
- 사용 : 들어온 순서가 중요한 값을 다룰 때
#### Hash
- `Hash` : 키 하나 안에 필드를 나눠서 저장 가능
  ``` plain text
  HSET user:1 name "민지" age "27"
  HGET user:1 name  → "민지"
  ```
  - `name`과 `age`는 각각 필드 이름이 됨
  - String에서와 달리, `HGET`은 필드 `name`을 실제로 지정해서 읽음
- 사용 : 한 데이터에 관한 값 여러 개를 한 키 아래 묶어 다룰 때 유용
#### Set
- `Set` : 중복을 허용하지 않고, 순서를 보장하지 않는 데이터 묶음
  ``` plain text
  SADD article:1:tags "redis" "database" "redis"
  SMEMBERS article:1:tags  → "redis", "database"  # 표시 순서는 달라질 수 있음
  ```
- 사용 : 포함 여부가 중요하고 순서는 중요하지 않은 경우
#### Sorted Set
- `Sorted Set` : 중복을 허용하지 않지만, 각 멤버에 숫자 점수를 붙여 점수순으로 볼 수 있다.
  ``` plain text
  ZADD ranking 80 "user:1" 95 "user:2"
  ZREVRANGE ranking 0 -1  → "user:2", "user:1"
  ```
  - ranking은 Redis 키 하나
  - ranking의 value에 `("user:1", 80)`, `("user:2", 95)`가 들어 있음
  - "user:1"은 Hash가 아니라 멤버를 식별하는 **문자열**일 뿐임
  - `ZREVRANGE` : 점수가 높은 순서대로 멤버를 읽음

---

## 원자적 명령
- 문제 상황 : 두 요청이 동시에 기존 값을 읽고, 각각 업데이트 해버림 → 값은 마지막 업데이트만 반영이 됨
- 해결 : 원자적 명령
- `INCR` : 값을 읽고 증가시켜 저장하는 작업을 Redis 명령 하나로 처리 ("읽고-계산하고-쓰기"를 한 번에)
  - value가 String일 때 사용 가능하다 (각 자료구조를 조작하는 명령이 따로 있으므로 Hash, List 등에 사용 불가)
  - 저장된 String 값이 정수로 해석 가능해야 한다.

---

## 접속 방식
> **Redis에 어떻게 명령을 보내는가?**
> <br> Redis를 사용한다는 것은, Redis 서버에 명령을 보내고 서버가 돌려준 결과를 받는다는 뜻
- 명령을 보내는 방법
  ``` plain text
  사람 ── redis-cli ──┐
                     ├── Redis 서버 ── 결과를 돌려줌
  프로그램 ── 라이브러리 ─┘
  ```
#### redis-cli 
- 터미널에서 Redis 서버에 연결하는 별도의 프로그램 (사람이 터미널에서 시험해볼 때 사용)
- 터미널에서 redis-cli 열어서 다음과 같은 명령을 입력할 수 있음
  ``` plain text
  SET greeting "안녕"
  GET greeting
  ```
#### 언어별 클라이언트 라이브러리 
- 애플리케이션 코드에서 해당 언어의 Redis 클라이언트 라이브러리 사용
- 파이썬 예시
  ``` plain text
  client.get("greeting")
  ```
  - 라이브러리가 Redis 서버에 `GET greeting`에 해당하는 요청을 보내고 응답을 받아옴


<br>
<br>

---

<p align="right">
  <a href="./02-when-to-use.md">⬅ 이전 페이지</a>
  &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
  <a href="./04-hash-table.md">다음 페이지 ➡</a>
</p>