[⬅ overview](./00-overview.md)

# 1. Redis는 왜 등장했나 (역사와 배경)

> - 디스크 기반 DB의 한계: 반복되는 조회, 디스크 I/O 비용
> - 캐시의 등장: 자주 쓰는 데이터를 메모리에 키 → 값으로 저장 (Memcached)
> - Memcached의 한계: 구조 없는 값, 디스크 저장 불가, 일부만 수정하기 어려움
> - Redis의 탄생(2009): 메모리 속도 + 서버가 이해하는 자료구조 + 선택 가능한 영속성
> - 이후의 흐름: 캐시를 넘어 세션, 랭킹, 큐 등으로 확장, DB와의 공존

---

<br>
<br>

---

<p align="right">
  <a href="./00-overview.md">⬅ 이전 페이지</a>
  &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
  <a href="./02-when-to-use.md">다음 페이지 ➡</a>
</p>