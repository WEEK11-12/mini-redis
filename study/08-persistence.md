[⬅ overview](./00-overview.md)

---

# 8. 서버 다운 대비: 영속성 (Optional)
> - 메모리 저장소의 약점: 서버가 꺼지면 데이터가 사라짐
> - RDB: 주기적 스냅샷, 구현이 쉽지만 마지막 시점 이후 유실 가능
> - AOF: 쓰기 명령 로그 누적, 재시작 시 재실행으로 복구
> - 트레이드오프: 안전성, 성능, 구현 난이도
> - 복구 시 만료된 데이터 처리

<br>
<br>

---

<p align="right">
  <a href="./07-interface-design.md">⬅ 이전 페이지</a>
  &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;
  <a href="./09-testing.md">다음 페이지 ➡</a>
</p>