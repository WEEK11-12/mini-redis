# 3단계 요구사항 명세서 — 외부 HTTP 사용과 API 응답 재사용

- 상태: 3단계 범위·인수 조건 확인 완료 — 구현·실행 검증 전
- 적용 범위: HTTP 요청을 2단계 해시 테이블 저장소에 연결하고 API 응답을 저장·재사용하는 기능 사례. 실제 만료·무효화(4단계), 동시성 방어(5단계), 성능 비교·전체 검증(6단계)은 제외한다.
- 근거: [과제 원문](../../assignment.md), [1단계 공유 계약](../01-scope-and-contract/overview.md), [D-0002 Python·HTTP API](../../decisions/0002-python-http-interface.md), [D-0003 기본 HTTP 계약](../../decisions/0003-http-response-contract.md), [D-0004 HTTP 키 제약](../../decisions/0004-http-key-no-slash.md), [D-0005 3단계 HTTP 경계](../../decisions/0005-http-api-boundary.md), [2단계 저장소 요구사항](../02-hash-table/requirements.md), [3단계 설계](design.md), [3단계 개요](overview.md)

## 식별·상태

- ID는 `REQ-03-001`처럼 단계 번호와 일련번호를 사용한다. 아래 **명세**는 이번 단계에서 기대하는 동작이고 **인수 조건**은 실행으로 확인할 기준이다. 현재 인수 조건을 통과했다는 뜻은 아니다.
- 기존 기본 계약과 승인된 3단계 키·라우팅·본문·원본 예시의 경계를 반영했다. 자세한 경로 분류 우선순위와 실패·연결 처리, 실행 흐름은 [설계 문서](design.md)에 유지한다. 범위 확정은 인수 조건 통과의 증거가 아니다.
- 구현 전 통합 TC는 `test-cases.md`에, 실제 구현·검증 결과는 작업 후 `implementation.md`·`verification.md`에 각각 기록한다. 현재는 세 파일 모두 작성 전이다.

## 기능 요구사항

### REQ-03-001 — 저장·덮어쓰기의 외부 호출

- **명세:** HTTP `PUT /keys/{key}`에 `{"value": "..."}`로 문자열 값을 보내면 같은 키의 값을 저장하거나 덮어쓴다. 빈 문자열 값도 허용하며, 성공 응답은 `200`·`{"stored": true}`다.
- **인수 조건:** 외부 HTTP 요청으로 값을 저장·재저장한 뒤 같은 키를 조회하면 마지막 값만 나온다. 빈 문자열을 저장한 키도 존재하는 값으로 조회된다.
- **근거:** [D-0003 기본 연산 계약](../../decisions/0003-http-response-contract.md#결정), [REQ-02-001](../02-hash-table/requirements.md#req-02-001--저장과-덮어쓰기).

### REQ-03-002 — 조회·미존재 구별

- **명세:** `GET /keys/{key}`는 값이 있으면 `200`·`{"value": "..."}`를 반환한다. 없는 키는 `404`·`{"error": {"code": "KEY_NOT_FOUND"}}`를 반환한다. 빈 문자열 값은 미존재로 취급하지 않는다.
- **인수 조건:** 저장된 일반 값과 빈 문자열은 각각 `200`으로 정확히 조회되고, 저장하지 않았거나 삭제한 키는 `404`와 `KEY_NOT_FOUND`로 구별된다.
- **근거:** [D-0003 기본 연산 계약](../../decisions/0003-http-response-contract.md#결정), [REQ-02-002](../02-hash-table/requirements.md#req-02-002--조회-결과-구분).

### REQ-03-003 — 존재 확인

- **명세:** `GET /keys/{key}/exists`는 저장된 키에 `200`·`{"exists": true}`, 없는 키에 `200`·`{"exists": false}`를 반환한다.
- **인수 조건:** 일반 값 또는 빈 문자열 값의 키는 `true`, 저장하지 않았거나 삭제한 키는 `false`다. 없는 키도 오류 응답이 아니다.
- **근거:** [D-0003 기본 연산 계약](../../decisions/0003-http-response-contract.md#결정), [REQ-02-003](../02-hash-table/requirements.md#req-02-003--존재-확인).

### REQ-03-004 — 삭제

- **명세:** `DELETE /keys/{key}`는 실제 삭제했으면 `200`·`{"deleted": true}`, 키가 없으면 `200`·`{"deleted": false}`를 반환한다.
- **인수 조건:** 저장된 키의 첫 삭제는 `true`, 같은 키의 재삭제와 없는 키의 삭제는 `false`다. 삭제 후 조회는 `404`이고 다른 키는 그대로 조회된다.
- **근거:** [D-0003 기본 연산 계약](../../decisions/0003-http-response-contract.md#결정), [REQ-02-004](../02-hash-table/requirements.md#req-02-004--삭제).

### REQ-03-005 — 입력 거부와 내부 오류 구별

- **명세:** HTTP 키는 비어 있지 않은 ASCII 영숫자·`-_.~` 조합으로 제한하고 키 전체 `.`·`..`와 퍼센트 인코딩은 거부한다. 별도의 키 길이 상한은 없다. 구분 가능한 잘못된 키 경로는 `400 INVALID_KEY`, 정의된 경로의 쿼리는 `400 INVALID_QUERY`, 미지원 메서드는 `405 METHOD_NOT_ALLOWED`와 해당 경로의 `Allow`, 미정의 경로는 `404 ROUTE_NOT_FOUND`로 구별한다. `PUT`은 정확히 `Content-Type: application/json`의 UTF-8 JSON 객체에서 문자열 `value` 필드 하나만 받아들이고 선언 길이 최대 64 KiB를 적용한다. 본문·길이·전송 인코딩 오류는 `400 INVALID_BODY`로 거부하며 예상 밖 내부 오류는 세부 정보 없는 `500 INTERNAL_ERROR`로 구별한다. 저장소 자체의 키 계약은 바꾸지 않는다.
- **인수 조건:** `/keys/`, `/keys/a/b`, `/keys/a%2Fb`, `/keys/%61`, 원시 경로에서 확인 가능한 `/keys/.`·`/keys/..`는 `400 INVALID_KEY`이고 저장소 값은 유지된다. `POST /keys/a`는 `405`와 `Allow`, `POST /unrelated`는 `404 ROUTE_NOT_FOUND`, 정의된 경로의 쿼리는 `400 INVALID_QUERY`다. 잘못된 JSON·누락/비문자열/추가 필드·미디어 유형/매개변수 오류·64 KiB 초과 선언·중복/비정상 `Content-Length`·`Transfer-Encoding`은 `400 INVALID_BODY`이며 저장소를 호출하지 않는다. 빈 문자열 값은 허용한다. 제어된 내부 실패는 `500 INTERNAL_ERROR`이고 내부 상세가 노출되지 않는다. 원래 경로가 중간 계층에서 정규화된 경우 서버가 복원하거나 동일한 키 오류를 반환하는 것은 보장하지 않는다. 경계별 처리 순서와 연결 종료 범위는 [설계](design.md#2-기본-http-인터페이스와-입력-계약)를 따른다.
- **근거:** [D-0003 입력·오류 계약](../../decisions/0003-http-response-contract.md#결정), [D-0004 HTTP 키 제약](../../decisions/0004-http-key-no-slash.md), [D-0005 채택 계약](../../decisions/0005-http-api-boundary.md), [REQ-02-005](../02-hash-table/requirements.md#req-02-005--잘못된-입력-거부).

### REQ-03-006 — HTTP 응답의 캐시 방지

- **명세:** Mini Redis 애플리케이션이 생성·전송하는 모든 최종 HTTP 응답에 `Cache-Control: no-store`를 넣어 HTTP 중간 캐시와 서비스 내부의 키-값 캐시를 구분한다. 파싱 전에 서버가 거부하거나 연결이 끊긴 요청은 이 보장의 대상이 아니다.
- **인수 조건:** 정상 결과·미존재·입력 오류·미지원 메서드·미정의 경로·제어된 내부 오류 응답에 헤더가 있다. `HEAD` 오류 응답에는 상태·해당 헤더를 적용하되 본문은 전송하지 않는다.
- **근거:** [D-0003 기본 HTTP 계약](../../decisions/0003-http-response-contract.md#결정).

### REQ-03-007 — API 응답 저장·재사용 기능 사례

- **명세:** Mini Redis 밖의 별도 로컬 원본 API `GET /items/demo`의 문자열 `sample-response`를 외부 one-shot 클라이언트가 HTTP 키 `example-demo`에 저장하고 다음 호출에서 재사용한다. `GET /origin-calls`로 실제 원본 데이터 요청 횟수를 관찰한다. 두 서버는 별도 장기 실행 프로세스로 두고 재시작으로 상태를 초기화한다.
- **인수 조건:** 빈 저장소와 호출 횟수 `0`에서 첫 클라이언트 실행은 `404 KEY_NOT_FOUND`에만 반응하여 원본을 호출·저장하고 `sample-response`를 반환하며 횟수가 `1`이 된다. 두 번째 실행은 같은 값을 저장소에서 반환하고 원본 호출 횟수는 `1` 그대로다. 빈 문자열의 `200`은 히트로 취급하고 캐시 장애·원본 실패·저장 실패를 성공한 재사용으로 보고하지 않는다. 횟수 조회는 카운터를 증가시키지 않는다. 재현 절차·실패 흐름은 [설계](design.md#4-외부-사용-예제의-흐름과-실패)를 따른다.
- **근거:** [과제 원문 품질 항목](../../assignment.md#품질), [구현 단위 가이드 3단계](../../plans/implementation-units.md#3-외부-사용-경로와-활용-사례), [3단계 예시 설계](design.md#4-외부-사용-예제의-흐름과-실패).

## 연결·검증 요구사항

### REQ-03-008 — 저장소 연결과 통합 검증

- **명세:** HTTP 처리부는 요청·응답 변환을 맡고, 키-값 연산은 기존의 직접 구현한 저장소를 사용한다. 외부 HTTP 요청과 실제 저장소를 연결한 기능 테스트로 이번 단계의 동작·경계를 확인하고 기존 저장소 단위 테스트를 유지한다.
- **인수 조건:** 코드 검토에서 HTTP 처리부가 저장소 버킷을 직접 조작하거나 다른 핵심 키-값 저장소로 대체하지 않음을 확인한다. 실제 저장소를 이용한 외부 요청 테스트에서 `REQ-03-001`~`REQ-03-007`의 확정된 인수 조건을 확인하고, 저장소 단위 테스트의 재실행 명령·조건·실제 결과를 기록한다. 미실행 조건은 완료로 표시하지 않는다.
- **근거:** [D-0002 책임 경계](../../decisions/0002-python-http-interface.md#결정과-영향), [1단계 공유 계약](../01-scope-and-contract/overview.md#확인된-공유-계약과-책임-경계), [단계별 산출물 가이드](../../plans/iteration-deliverables.md#단계에-따른-테스트-경계).

## 확정된 경계와 구현 전 확인

HTTP 키의 슬래시 제외는 [D-0004](../../decisions/0004-http-key-no-slash.md), 추가 문자·라우팅·본문·오류의 공통 계약은 [D-0005](../../decisions/0005-http-api-boundary.md)에서 확정했다. 원본 API 활용 사례의 구체적 동작은 [3단계 설계](design.md#4-외부-사용-예제의-흐름과-실패)에 둔다. 클라이언트 편의 검사는 서버의 HTTP 키 검증을 대체하지 않는다. 구현 전 TC에는 미지원 메서드의 기본 서버 응답 누출, 원시 경로 검증, `HEAD` 본문 부재, 비정상 길이·전송 인코딩 거부와 기존 저장 상태 보존을 포함한다. 설계 계약의 확정은 아직 실행 검증을 뜻하지 않는다. 실제 만료 키의 응답 계약은 [D-0003](../../decisions/0003-http-response-contract.md)에 이미 정해졌지만 만료 동작 구현·검증은 4단계다.
