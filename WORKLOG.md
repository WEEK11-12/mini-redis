# 작업 인계와 현재 상태

## 현재 단위

U1 저장·조회·삭제·충돌 처리 로컬 구현과 순차 테스트 완료. 사용자는 체이닝 삭제의 연결 보존을 확인하고 다음 작업 진행을 요청했다. 현재 작업은 사용자 요청에 따른 main-redis 통합과 개인 main 반영이다. 팀 main은 변경하지 않는다. 이 요청은 기존 U1 구현의 커밋·푸시도 포함한다.

## 실제 결과

- Python 3.13.14, 표준 unittest. 새 패키지 설치 없음.
- 제품: mini_redis/store.py, mini_redis/__init__.py. 테스트: tests/test_store.py. 캐시 제외: .gitignore.
- 미구현 골격 실행: 6개 테스트, 하위 사례 포함 8개 NotImplementedError, 종료 코드 1. 제품 버그 발견과 구분.
- 구현 후 `python -m unittest discover -s tests -v`: 6개 PASS, 종료 코드 0.
- 메모리에서만 고장 삭제를 대입한 실험: T-06이 세 assertion 실패로 검출. 제품 파일 변경 없음. 실제 수정한 버그가 있었다고 표현하지 않는다.
- 자세한 과정·이유·예시·한계: [U1 검증 기록](docs/verification/U1-storage.md).

## 미구현·미검증

입력 제한·확장·TTL·청소·Flask·Waitress HTTP는 아직 없다. U1 버킷은 16개 고정. 락은 있지만 동시 요청 테스트는 미실행. FNV 전체 알려진 벡터·부하·스트레스·성능도 미검증. 기본 설계의 남은 극단 입력은 REQUIREMENTS에 유지한다.

## 다음 작업과 진행 경계

1. U2 입력 경계·FNV 벡터·확장 테스트를 함께 구체화한다.
2. 잘못된 자료형 TypeError·길이 초과 ValueError는 제안 상태이며 사용자 확인 후 구현한다. U1 고장 주입 실험은 실제 버그 수정과 구분해 유지한다.
3. 임의로 다음 단위를 구현하거나 커밋·푸시하지 않는다.

## 기록 방식

결정이 필요하면 문제·조건과 대안의 이득·손해를 먼저 설명한다. 실제 명령·결과·실패·수정·재검증과 사용자가 확인한 상태를 남긴다. 미실행이나 사용자 미확인을 완료로 바꾸지 않는다.

## 로컬·Git 통합

- 기존 mini-redis, mini-redis-personal-main, mini-redis-study-jye를 main-redis 하나로 통합하고 원본 폴더 3개를 제거했다.
- 기존 세 폴더의 파일 212개를 ZIP으로 백업하고 SHA-256 일치를 확인했다. 백업은 작업 루트 밖이 아닌 상위 ai_week/.tmp/redis-consolidation-*에 있으며 Git에는 올리지 않는다. 기존 팀 체크아웃의 미커밋 README도 보존했다.
- 새 main-redis는 독립 .git을 가진 로컬 복제본이다. 공유 worktree의 .git 경로에 의존하지 않는다. 첫 복제는 Windows 하위 프로세스 생성 제한으로 실패했고, 같은 읽기·복제 작업을 승인된 권한으로 재실행해 성공했다.
- 원격 origin은 개인 레포, upstream은 팀 레포. 기존 study-jye와 yeongeun-main 브랜치 이력은 보존했다. 현재 노트 관리는 개인 main의 study/다.
- 코드·테스트와 노트는 복사 직후 원본과 바이트 일치를 확인했다. Markdown 22개와 상대 링크 123개 검사를 통과했다. 원본 폴더 제거 후 새 경로에서 U1 테스트 6개를 재실행해 모두 통과했고 Git 객체 연결 검사도 통과했다. worktree 목록은 main-redis 하나다. 커밋 후 개인 origin/main 푸시의 원격 SHA와 clean 상태를 별도로 확인한다.
