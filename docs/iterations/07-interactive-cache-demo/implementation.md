# 7단계 구현 기록 — 첫 정상 동작 흐름

- **상태:** 구현 완료. 정상 흐름, 캐시 장애 시 수명 단위 비활성화, 기록·요약, 로컬 요청 보호와 화면을 구현했다. 시험 및 확인 범위는 [검증 기록](verification.md)에 분리해 기재했다. 검토 판정은 실제로 확인한 범위에 한정한다.
- **경계:** `mini_redis/`와 1~6단계 파일은 변경하지 않았다. 테스트 DB는 메모리 이중물이고 캐시는 새 자식의 실제 Mini Redis HTTP 서버다.

| 파일 | 현재 역할 |
| --- | --- |
| `examples/interactive_cache.py` | 전용 빈 캐시 자식 기동·종료, 공개 HTTP GET/PUT/DELETE 호출, DB 컬렉션을 주입받는 저장·목록·읽기 흐름과 직렬화 잠금 |
| `examples/interactive_cache_page.py` | 루프백 페이지 서버, 키 목록·저장·읽기 JSON 경로, 요청 토큰·Host·Origin 검증, 별도 MongoDB 컬렉션을 선택하는 진입점 |
| `examples/interactive_cache_page.html` | 키·값 입력, 키별 읽기와 DB 직접 읽기, 결과·단발 소요 시간 표시 |
| `tests/test_interactive_cache.py` | 격리 DB 이중물과 실제 새 캐시 자식으로 도메인·HTTP 정상 경로 확인 |

저장은 DB upsert 뒤 해당 키의 캐시 DELETE를 요청한다. 첫 캐시 우선 읽기는 미스→DB→캐시 PUT이며 다음 읽기는 캐시 히트다. 직접 읽기는 캐시를 호출하지 않는다. DELETE 실패 시 수정 성공 안내에 읽기가 늦어질 수 있음을 덧붙이고 그 서버 수명 동안 캐시를 비활성화한다. GET/PUT/DELETE 실패 이중물 주입과 실제 불완전 HTTP 응답에서 이후 캐시 호출 없이 DB로 읽는다. HTTP 캐시 호출은 리다이렉트를 자동 추적하지 않는 `HTTPConnection`으로 제한한다. 입력은 저장 전 검증하고 `null`을 거부한다. 자식 기동 실패 때는 DB 전용 `Demo`로 시작하며 POST는 현재 Origin·Host·토큰을 확인한다. 실행 명령은 `python3 -B -m examples.interactive_cache_page`.


**추가 연결:** `TimingLog`는 `var/interactive-cache-demo/timings.jsonl`에 시각·키·동작·출처·시간·성패를 append/fsync하며 값을 기록하지 않는다. 화면의 `/api/timings`는 전체 유효 읽기 행의 출처별 횟수·평균·중앙값과 최근 50개, 실패·없는 키·잘못된 행 수를 제공한다. 기록 실패는 DB 결과를 바꾸지 않고 `timing_saved: false`로 알린다. 페이지 진입점은 같은 checkout의 중복 서버를 `flock` 잠금으로 거부한다. 테스트용 MongoDB 컨테이너와 브라우저에서 저장·수정·직접 읽기·캐시 첫 읽기/히트·서버 재시작 후 DB 목록/기록 유지와 새 빈 캐시를 관찰했다. 사용자의 기존 7단계 컨테이너에는 연결하지 않았다.

**독립 검증 지적 반영 (2026-11-19, 최소 수정 2건):** `CacheChild._request`는 기존 응답 크기 상한(262,144바이트)을 그대로 두고 그 뒤에 HTTP 메시지 완결성을 확인한다(`examples/interactive_cache.py` 95~97줄). 선언한 Content-Length만큼 받지 못했거나 선언보다 많은 바이트가 남아 있으면 JSON으로 파싱되더라도 `CacheUnavailable`을 던져 기존 경로대로 그 서버 수명 전체의 캐시 중단으로 이어진다. 화면(`examples/interactive_cache_page.html`)은 읽기를 시작할 때 결과 상자를 해당 키의 진행 문구로 바꾸고 실패 시 실패 문구로 덮어써, 직전 성공 값·출처·시간이 현재 결과처럼 남지 않는다. 결과에는 대상 키를 함께 표시한다. 실행 근거는 [검증 기록](verification.md)에 있다.

**경계:** 시연은 전용 컬렉션을 사용하며 기존 데이터에 접근하지 않는다. 실제 MongoDB 장애 시험은 미실행 한계이지 별도 인수 기준이 아니다. 늦은 DB 반영은 수용한 한계다. 엄격한 OS 소유 증명·고아 자동 회수, 여러 checkout의 DB 공유, 협력하지 않는 외부 프로그램의 직접 변경 보장은 범위 밖이다.
