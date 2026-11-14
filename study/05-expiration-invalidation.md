[⬅ overview](./00-overview.md)

---

# 5. 만료와 무효화
> - 만료 시간 저장 방식: 만료 시각(타임스탬프) vs 남은 시간
> - 만료된 값을 요청받았을 때의 처리: Lazy 삭제(조회 시 확인)
> - 만료된 키의 메모리 정리: Active 삭제(주기적 정리)와 트레이드오프
> - 데이터 무효화(deprecated): 명시적 삭제 API와 TTL
> - 캐시와 원본 DB의 불일치 문제
> - 엣지 케이스: 만료 직전 조회, TTL 갱신, 만료 후 같은 키 재저장

<br>
<br>

---

<p align="right">
  <a href="./04-hash-table.md">⬅ 이전 페이지</a>
  &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
  <a href="./06-concurrency.md">다음 페이지 ➡</a>
</p>