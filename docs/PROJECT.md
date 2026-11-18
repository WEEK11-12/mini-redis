# Mini Redis 프로젝트 개요

여러 프로그램이 HTTP로 접근하는 문자열 메모리 저장소입니다. Python으로 해시 테이블을 직접 만들고 Flask로 API를 제공하며 Waitress로 실행합니다.

## 목표와 범위

저장·조회·삭제, 충돌과 확장, TTL과 명시적 무효화, 동시 요청의 정확성, 외부 API 응답 캐싱과 성능 비교를 직접 경험하고 설명합니다. 수동 메모리 관리가 중심 과제가 아니므로 C에서 Python으로 변경했습니다.

| 항목 | 현재 상태 |
| --- | --- |
| 환경 | Windows, Python 3.13.14, Flask 3.1.3·Waitress 3.0.2를 .venv에 설치해 검증 |
| HTTP | Flask + Waitress, POST /set·/get·/delete |
| 실행 | 1프로세스, 요청 4스레드, 청소 1스레드, 공용 저장소·락 |
| 입력 | 문자열, 빈 키·값 허용, UTF-8 키 1 KiB·값 1 MiB |
| 영속성 | 초기 범위 제외. 종료하면 데이터 소멸 |
| 구현·검증 | U1~U7 필수 검증과 자동 테스트 57개 통과. 캐시 각 20회 순차 비교·청소 10,000키 부하 기록 있음. 동시 HTTP 부하·한계 스트레스는 미검증 |

실제 Redis의 모든 자료형, RESP, 트랜잭션, 분산 구조는 초기 범위가 아닙니다. 캐시 데모는 상품 1개·원본 50ms 대기·화면 TTL 1초로 구현했습니다. 총 메모리 한도·과부하 정책은 보장하지 않습니다.

## 현재 파일 배치

실제 구현은 mini_redis/store.py·expiration.py·api.py·server.py, 자동 검사는 tests/ 아래 저장소·TTL·청소·동시성·HTTP 테스트, 캐시 예제는 examples/, 실행 과정은 history/에 둡니다. 상세 폴더 설명은 [문서 지도](README.md)를 따릅니다.

## 사용 안내

[API](API.md)는 HTTP 계약이며 실제 연결 결과는 [U6 이력](../history/U6-http.md)에 기록했습니다. 설치·실행 명령은 [프로젝트 README](../README.md)를 따릅니다. 실행 순서는 [설계](DESIGN.md), 다음 단위는 [WORKLOG](../WORKLOG.md)를 따릅니다.

[문서 지도](README.md) · [요구사항](REQUIREMENTS.md) · [선택 이유](DECISIONS.md) · [테스트](TESTING.md)
