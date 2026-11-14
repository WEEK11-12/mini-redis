[⬅ overview](./00-overview.md)

---

# 2. 언제, 어떻게 Redis를 쓰나

> - 대표 사용처: 캐시, 세션, 조회수/카운터, 랭킹, 인증번호(TTL), 요청 제한
> - 서비스 구조에서의 위치: 앱 서버 ↔ Redis ↔ DB
> - 캐시 연동 방식: Cache-Aside(앱이 직접 처리)와 Read-Through
> - Redis가 맞지 않는 경우: 복잡한 조회/조인, 메모리보다 큰 데이터

<br>
<br>

---

<p align="right">
  <a href="./01-background.md">⬅ 이전 페이지</a>
  &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
  <a href="./03-how-to-use.md">다음 페이지 ➡</a>
</p>