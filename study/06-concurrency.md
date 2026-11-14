[⬅ overview](./00-overview.md)

---

# 6. 동시성 구조

> - 경쟁 상태(race condition): 조회수 증가 예시
> - Redis의 방식: 싱글 스레드 이벤트 루프와 I/O 멀티플렉싱
> - 멀티 스레드 방식: 뮤텍스, 읽기/쓰기 락과 락의 비용
> - 원자성 보장: 명령 단위의 순차 처리
> - 만료 정리 같은 백그라운드 작업과의 충돌
> - Mini Redis의 구조 선택: 순차 처리 vs 락 기반

<br>
<br>

---

<p align="right">
  <a href="./05-expiration-invalidation.md">⬅ 이전 페이지</a>
  &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
  <a href="./07-interface-design.md">다음 페이지 ➡</a>
</p>