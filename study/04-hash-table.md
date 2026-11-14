[⬅ overview](./00-overview.md)

---
# 4. 해시 테이블 설계와 구현 (과제의 핵심)

> - 왜 O(1)인가: 순차 탐색 O(N)과 해시 조회 비교
> - 해시 함수: 키를 배열 위치로 바꾸는 방법과 좋은 해시 함수의 조건
> - 충돌 처리: 체이닝과 오픈 어드레싱, 각각의 트레이드오프
> - 리사이징: 부하율(load factor), 테이블 확장과 재해싱
> - 주요 함수의 동작: put(set), get, delete, 키 갱신
> - 설명할 수 있어야 하는 것: 설계 원리, 구현 과정, 함수별 동작 방식
> - 참고: Redis dict의 점진적 리해싱

<br>
<br>

---

<p align="right">
  <a href="./03-how-to-use.md">⬅ 이전 페이지</a>
  &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
  <a href="./05-expiration-invalidation.md">다음 페이지 ➡</a>
</p>