// Screen of the iteration 07 live benchmark (served inline by examples/live_benchmark.py).
// Uses only the adopted local API; every server string goes into the DOM via textContent.
"use strict";

const CONDITIONS = ["no_cache", "miss", "hit"];
const CONDITION_LABEL = { no_cache: "캐시 미사용", miss: "캐시 미스", hit: "캐시 히트" };
const STATE_LABEL = {
  not_ready: "준비 전", preparing: "준비 중", seed_required: "시드 필요", ready: "준비 완료",
  failed: "준비 실패", recovery_required: "복구 필요",
};
const RUN_LABEL = { preparing: "측정 준비 중", running: "측정 중", succeeded: "성공", failed: "실패",
                    timed_out: "시간 초과" };
const STEP_LABEL = {
  checking_docker: "Docker 확인", checking_image: "이미지 확인", pulling_image: "이미지 받는 중",
  preparing_volumes: "전용 볼륨 확인", starting_container: "전용 컨테이너 시작",
  waiting_mongo: "MongoDB 응답 대기", checking_seed: "시드 읽기 전용 검사", seeding: "시드 생성 중",
  rechecking_seed: "시드 재검사", checking_resources: "전용 자원 재확인",
  inspecting_resources: "전용 자원 재확인", restarting: "측정 전 MongoDB 재시작",
  verifying_restart: "재시작 확인(문서 읽지 않음)", running_benchmark: "측정기 실행 중",
  judging: "원자료 판정",
};
const RECOVER = "서버를 멈춘 뒤 터미널에서 `python3 -B -m examples.live_benchmark --recover`로 " +
  "대상 작업·프로세스 종료를 확인·기록해야 다시 준비할 수 있습니다. 화면의 버튼이나 서버 재시작만으로는 풀리지 않습니다.";
const NOT_RECOVERABLE = ["SHARED_RECORD_MISSING", "SHARED_RECORD_UNVERIFIED", "SHARED_RECORD_UNREADABLE"];
const GUIDE = {
  BUSY: "다른 준비·시드·측정 작업이 진행 중입니다. 끝난 뒤 다시 시도하세요.",
  NOT_READY: "준비가 끝나지 않았습니다. 먼저 준비를 실행하세요.",
  SEED_NOT_REQUIRED: "현재 상태에서는 시드 재생성을 받지 않습니다(시드 필요 상태에서만 가능).",
  CONFIRMATION_REQUIRED: "시드 재생성은 컬렉션 삭제 영향을 확인해야 요청할 수 있습니다.",
  RECOVERY_REQUIRED: RECOVER,
  RECORD_UNAVAILABLE: "작업 기록을 저장하지 못했습니다. 저장 공간·권한을 확인하세요. " + RECOVER,
  FORBIDDEN_REQUEST: "127.0.0.1 주소로 연 로컬 화면의 요청만 허용합니다. 서버를 다시 시작했다면 페이지를 새로고침하세요.",
  RESOURCE_CONFLICT: "같은 이름의 컨테이너·볼륨이 이 시연의 소유 표지를 갖고 있지 않습니다. 해당 자원은 건드리지 않았으니 직접 확인하세요.",
  RESOURCE_MISMATCH: "전용 자원의 설정(이미지·포트·메모리·캐시·볼륨 연결)이 다릅니다. 자동으로 다시 만들지 않으니 소유 표지·설정을 수동으로 확인하세요.",
  PORT_CONFLICT: "127.0.0.1:27018 포트를 다른 프로그램이 쓰고 있습니다. 그 프로그램을 확인한 뒤 다시 준비하세요.",
  DOCKER_UNAVAILABLE: "Docker를 사용할 수 없습니다. Docker를 실행한 뒤 다시 준비하세요.",
  IMAGE_PULL_FAILED: "mongo:7 이미지를 받지 못했습니다. 네트워크를 확인한 뒤 다시 준비하세요.",
  CONTAINER_START_FAILED: "전용 컨테이너를 시작하지 못했습니다. Docker 로그를 확인한 뒤 다시 준비하세요.",
  MONGO_NOT_READY: "MongoDB가 제한 시간 안에 응답하지 않았습니다. 잠시 뒤 다시 준비하세요.",
  SEED_CHECK_FAILED: "시드 검사 자체(연결·조회)가 실패했습니다. 데이터는 바꾸지 않았습니다. 연결 상태를 확인하세요.",
  MEASUREMENT_CONDITION_UNMET: "저장 크기가 캐시 한도의 2배보다 작아 측정 조건을 만족하지 않습니다. 시드 재생성만으로 해결된다고 보장할 수 없습니다.",
  SEED_FAILED: "시드 생성 또는 생성 뒤 검사가 실패했습니다. 작업 로그를 확인한 뒤 확인을 거쳐 다시 생성할 수 있습니다.",
  SEED_TIMEOUT: "시드 생성이 제한 시간을 넘어 중단했습니다. 컬렉션이 불완전할 수 있으니 확인을 거쳐 다시 생성하세요.",
  SEED_REQUIRED: "시드가 없거나 예상 값과 다릅니다. 삭제 영향을 확인한 뒤 재생성할 수 있습니다.",
  SEED_MISMATCH: "측정 직전 시드 검사가 맞지 않아 측정하지 않았습니다. 확인을 거쳐 시드를 재생성하세요.",
  RESTART_FAILED: "측정 전 MongoDB 재시작 또는 재시작 확인에 실패해 측정하지 않았습니다. 다시 준비하세요.",
  BENCHMARK_FAILED: "측정기가 정상 종료하지 않았거나 결과 파일이 없습니다. 실행 디렉터리의 로그를 확인하세요.",
  RESULT_INVALID: "측정기는 끝났지만 결과 파일이 성공 조건을 만족하지 않아 수치를 표시하지 않습니다.",
  TIMED_OUT: "측정기가 제한 시간을 넘어 중단했습니다. 남은 원자료가 있으면 부분 수만 표시합니다.",
  SERVER_STOPPED: "서버가 종료 요청을 받아 작업을 멈췄습니다.",
  SERVER_INTERRUPTED: "서버가 작업 도중 비정상 종료됐습니다. " + RECOVER,
  INTERNAL_ERROR: "예상하지 못한 서버 오류로 작업을 실패로 끝냈습니다. 서버 로그와 작업 기록을 확인하세요.",
  SHARED_RECORD_MISSING: "공유 복구 기록이 없는데 전용 자원이 이미 있습니다. 이전 작업이 남아 있지 않은지 수동으로 확인해야 합니다.",
  SHARED_RECORD_UNVERIFIED: "공유 복구 기록이 없고 Docker로 전용 자원 부재를 확인하지 못했습니다. Docker를 실행한 뒤 서버를 다시 시작하세요.",
  SHARED_RECORD_UNREADABLE: "공유 복구 기록을 읽을 수 없습니다. 수동 조사가 필요합니다.",
  RUN_NOT_FOUND: "해당 실행 기록이 없습니다.",
};

function isCount(v) { return Number.isInteger(v) && v >= 0; }
function isMs(v) { return typeof v === "number" && Number.isFinite(v) && v >= 0; }
function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

function guideFor(code) {
  return GUIDE[code] || "알 수 없는 오류입니다. 서버 응답의 코드와 실행 기록을 확인하세요.";
}

function stepLabel(step) {
  return step ? (STEP_LABEL[step] || step) : "";
}

function controls(setup) {
  const none = { setup: false, seed: false, run: false };
  if (!isObject(setup) || setup.active_job != null) return none;
  const state = setup.state;
  // unknown, preparing and recovery_required states never offer new work
  if (!["not_ready", "seed_required", "ready", "failed"].includes(state)) return none;
  return { setup: true, seed: state === "seed_required", run: state === "ready" };
}

function banner(setup) {
  if (!isObject(setup)) {
    return { state: "unknown", label: "상태 확인 불가", message: "서버 상태를 읽지 못했습니다.", guide: "" };
  }
  const label = STATE_LABEL[setup.state] || "알 수 없는 상태";
  const code = setup.error && setup.error.code;
  // recovery first: whatever a run record still says, no new work is allowed
  if (setup.state === "recovery_required") {
    // --recover cannot settle an absent, unverifiable or unreadable shared record
    const guide = NOT_RECOVERABLE.includes(code) ? guideFor(code) : RECOVER;
    return { state: "recovery_required", label, message: setup.message || "", guide, code };
  }
  return { state: setup.state, label, message: setup.message || "", guide: code ? guideFor(code) : "", code };
}

// Polling without overlap: a regular tick is skipped while one is in flight, a forced tick
// (after a POST) always runs, and a response older than the last applied one is dropped.
function createPoller(fetchState, apply) {
  let issued = 0;
  let applied = 0;
  let inFlight = 0;
  return {
    async tick(options = {}) {
      if (inFlight > 0 && !options.force) return "skipped";
      const seq = ++issued;
      inFlight += 1;
      let state;
      try {
        state = await fetchState();
      } finally {
        inFlight -= 1;
      }
      if (seq < applied) return "stale";
      applied = seq;
      apply(state);
      return "applied";
    },
  };
}

function validResult(result) {
  if (!isObject(result) || !isObject(result.conditions) || !isObject(result.method) ||
      !isObject(result.environment)) return false;
  const keys = Object.keys(result.conditions).sort();
  if (keys.join() !== [...CONDITIONS].sort().join()) return false;
  return CONDITIONS.every((c) => {
    const row = result.conditions[c];
    return isObject(row) && isMs(row.median_ms) && isMs(row.p90_ms) &&
      row.successes === 100 && row.failures === 0;
  });
}

function partialRows(partial) {
  if (!isObject(partial) || !isObject(partial.conditions)) return null;
  const rows = [];
  for (const c of CONDITIONS) {
    const row = partial.conditions[c];
    if (!isObject(row) || !isCount(row.successes) || !isCount(row.failures)) return null;
    rows.push({ condition: c, successes: row.successes, failures: row.failures });
  }
  return rows;
}

function pick(row) {
  return { median_ms: row.median_ms, p90_ms: row.p90_ms, successes: row.successes, failures: row.failures };
}

function runView(run, setup) {
  if (!isObject(run)) return { kind: "none" };
  const base = { runId: run.run_id, label: RUN_LABEL[run.state] || "알 수 없는 상태",
                 artifacts: run.artifacts || null };
  if (run.state === "preparing" || run.state === "running") {
    const live = isObject(setup) && setup.state !== "recovery_required" && isObject(setup.active_job) &&
      setup.active_job.run_id === run.run_id;
    if (!live) {
      return { ...base, kind: "stale",
               message: "이 실행 기록은 종결되지 않았지만 서버에서 진행 중인 작업이 아닙니다. 결과로 보지 않습니다." };
    }
    return { ...base, kind: "progress", step: stepLabel(run.step) };
  }
  if (run.state === "succeeded") {
    if (!validResult(run.result)) {
      return { ...base, kind: "invalid", message: "성공 기록의 결과 형식을 확인할 수 없어 수치를 표시하지 않습니다." };
    }
    const r = run.result;
    return { ...base, kind: "success",
             rows: CONDITIONS.map((c) => ({ condition: c, ...pick(r.conditions[c]) })),
             method: r.method, environment: r.environment,
             mongoAfterUnavailable: r.environment.mongo_after_unavailable === true };
  }
  if (run.state === "failed" || run.state === "timed_out") {
    const p = partialRows(run.partial);
    return { ...base, kind: "failure", error: run.error || null, step: stepLabel(run.step),
             partialRows: p, aborted: p && run.partial.aborted != null ? String(run.partial.aborted) : null };
  }
  return { ...base, kind: "invalid", message: "알 수 없는 실행 상태입니다." };
}

function seedRequest(confirmed) {
  return confirmed === true ? { confirm_replace: true } : null;
}

if (typeof module !== "undefined") {
  module.exports = { controls, banner, runView, validResult, guideFor, stepLabel, seedRequest, createPoller,
                     CONDITIONS };
}

// ---------------------------------------------------------------- browser wiring
if (typeof document !== "undefined") {
  (function () {
    const token = document.querySelector('meta[name="live-bench-token"]').getAttribute("content");
    const $ = (id) => document.getElementById(id);
    let lastSetup = null;
    let lastRun = null;
    let pending = false;

    function el(tag, text, cls) {
      const node = document.createElement(tag);
      if (text != null) node.textContent = String(text);
      if (cls) node.className = cls;
      return node;
    }

    function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

    function showError(code, message) {
      const box = $("error-view");
      clear(box);
      if (!code) { box.hidden = true; return; }
      box.hidden = false;
      box.appendChild(el("strong", code));
      if (message) box.appendChild(el("p", message));
      box.appendChild(el("p", guideFor(code), "guide"));
    }

    async function api(method, path, body) {
      const options = { method, headers: {}, cache: "no-store", credentials: "same-origin" };
      if (method === "POST") {
        options.headers["Content-Type"] = "application/json";
        options.headers["X-Live-Bench-Token"] = token;
        options.body = JSON.stringify(body);
      }
      const response = await fetch(path, options);
      let data = null;
      try { data = await response.json(); } catch (e) { data = null; }
      return { status: response.status, data };
    }

    async function post(path, body) {
      if (pending) return;
      pending = true;
      render();
      try {
        const { status, data } = await api("POST", path, body);
        if (status === 202) {
          showError(null);
        } else {
          const error = data && data.error ? data.error : { code: "HTTP_" + status, message: "" };
          showError(error.code, error.message);
        }
      } catch (e) {
        showError("NETWORK", "서버에 연결하지 못했습니다.");
      } finally {
        pending = false;
        $("seed-confirm").checked = false;
        await refresh({ force: true });
      }
    }

    function table(headers, rows) {
      const t = el("table");
      const head = el("tr");
      headers.forEach((h) => head.appendChild(el("th", h)));
      t.appendChild(head);
      rows.forEach((cells) => {
        const tr = el("tr");
        cells.forEach((c) => tr.appendChild(el("td", c)));
        t.appendChild(tr);
      });
      return t;
    }

    function fmt(ms) { return ms.toFixed(3); }

    function chart(rows) {
      const max = Math.max(...rows.map((r) => r.p90_ms), 1e-9);
      const box = el("div", null, "chart");
      rows.forEach((r) => {
        const group = el("div", null, "bar-group");
        group.appendChild(el("div", CONDITION_LABEL[r.condition], "bar-label"));
        [["중앙값", r.median_ms, "median"], ["P90", r.p90_ms, "p90"]].forEach(([name, value, cls]) => {
          const line = el("div", null, "bar-line");
          line.appendChild(el("span", name, "bar-name"));
          const track = el("span", null, "bar-track");
          const bar = el("span", null, "bar " + cls);
          bar.style.width = Math.max(0.5, (value / max) * 100) + "%";  // CSSOM, allowed by the CSP
          track.appendChild(bar);
          line.appendChild(track);
          line.appendChild(el("span", fmt(value) + " ms", "bar-value"));
          group.appendChild(line);
        });
        box.appendChild(group);
      });
      return box;
    }

    function artifacts(view, box) {
      if (!view.artifacts) return;
      box.appendChild(el("p", "원자료 위치: " + view.artifacts.dir));
      const files = view.artifacts.files || {};
      const names = Object.keys(files).filter((name) => files[name] === true);
      box.appendChild(el("p", "남은 파일: " + (names.length ? names.join(", ") : "없음")));
    }

    function renderRun() {
      const box = $("run-view");
      clear(box);
      const view = runView(lastRun, lastSetup);
      box.dataset.kind = view.kind;
      if (view.kind === "none") { box.appendChild(el("p", "아직 실행 기록이 없습니다.")); return; }
      box.appendChild(el("p", "실행 ID: " + view.runId + " · 상태: " + view.label, "run-head"));
      if (view.kind === "progress") {
        box.appendChild(el("p", "진행 단계: " + (view.step || "-") +
          " (측정기는 중간 진행률을 내지 않으므로 퍼센트·조건별 수치는 표시하지 않습니다.)"));
      } else if (view.kind === "stale" || view.kind === "invalid") {
        box.appendChild(el("p", view.message, "warn"));
        artifacts(view, box);
      } else if (view.kind === "success") {
        box.appendChild(el("h3", "세 조건 비교 (중앙값·P90, ms) — 이 실행의 원자료"));
        box.appendChild(chart(view.rows));
        box.appendChild(table(["조건", "중앙값(ms)", "P90(ms)", "성공", "실패"], view.rows.map((r) =>
          [CONDITION_LABEL[r.condition], fmt(r.median_ms), fmt(r.p90_ms), r.successes, r.failures])));
        const m = view.method;
        box.appendChild(el("h3", "측정 방법"));
        box.appendChild(table(["항목", "값"], [
          ["예열(집계 제외)", m.warmup_per_condition + "회/조건"], ["측정", m.rounds + "회/조건, 순차 실행"],
          ["키 분산", "회차마다 다른 키 (seed " + m.key_seed + ", 범위 " + m.key_space + ")"],
          ["타이머", m.timer], ["백분위", m.percentile]]));
        const env = view.environment;
        const before = isObject(env.mongo_before) ? env.mongo_before : {};
        const runner = isObject(env.runner) ? env.runner : {};
        const precheck = isObject(runner.precheck) ? runner.precheck : {};
        box.appendChild(el("h3", "실행 환경·조건"));
        box.appendChild(table(["항목", "값"], [
          ["Python", env.python], ["플랫폼", env.platform + " / " + env.machine], ["커밋", env.commit],
          ["측정 시작(UTC)", runner.measured_at || "-"], ["MongoDB 이미지 ID", runner.image_id || "-"],
          ["측정 전 문서 수", before.count], ["캐시 한도(bytes)", before.cache_max_bytes],
          ["저장 크기(bytes)", before.storage_bytes != null ? before.storage_bytes : "-"],
          ["사전 시드 검사(재시작 전)", precheck.checked_at || "-"],
          ["측정 후 MongoDB 정보", view.mongoAfterUnavailable ? "확인 불가(측정 후 수집 실패)" : "수집됨"]]));
        artifacts(view, box);
      } else if (view.kind === "failure") {
        const error = view.error || {};
        box.appendChild(el("p", "단계: " + (view.step || "-") + " · 코드: " + (error.code || "-")));
        if (error.message) box.appendChild(el("p", error.message));
        if (error.code) box.appendChild(el("p", guideFor(error.code), "guide"));
        if (view.partialRows) {
          box.appendChild(el("h3", "남은 원자료의 실제 성공·실패 수 (완결 결과 아님, 비교 그래프 없음)"));
          box.appendChild(table(["조건", "성공", "실패"], view.partialRows.map((r) =>
            [CONDITION_LABEL[r.condition], r.successes, r.failures])));
          if (view.aborted) box.appendChild(el("p", "중단 사유: " + view.aborted));
        } else {
          box.appendChild(el("p", "표시할 수 있는 원자료 수치가 없습니다."));
        }
        artifacts(view, box);
      }
    }

    function render() {
      const b = banner(lastSetup);
      $("status").dataset.state = b.state;
      $("status-state").textContent = b.label;
      $("status-message").textContent = b.message;
      $("status-guide").textContent = b.guide;
      $("status-step").textContent = lastSetup && lastSetup.step ? "진행 단계: " + stepLabel(lastSetup.step) : "";
      const job = lastSetup && lastSetup.active_job;
      $("status-job").textContent = job ? "진행 중 작업: " + job.kind + (job.run_id ? " (" + job.run_id + ")" : "") : "";
      const can = controls(lastSetup);
      $("setup-button").disabled = pending || !can.setup;
      $("run-button").disabled = pending || !can.run;
      $("seed-confirm").disabled = pending || !can.seed;
      $("seed-button").disabled = pending || !can.seed || !$("seed-confirm").checked;
      renderRun();
    }

    async function fetchState() {
      try {
        const response = await api("GET", "/api/setup");
        const setup = response.status === 200 ? response.data : null;
        const job = setup && setup.active_job;
        const id = setup && ((job && job.run_id) || setup.last_run_id);
        if (!id) return { setup, run: null };
        const run = await api("GET", "/api/runs/" + encodeURIComponent(id));
        return { setup, run: run.status === 200 ? run.data : null };
      } catch (e) {
        return { setup: null, run: null };
      }
    }

    const poller = createPoller(fetchState, (state) => {
      lastSetup = state.setup;
      lastRun = state.run;
      render();
    });

    function refresh(options) { return poller.tick(options); }

    $("setup-button").addEventListener("click", () => post("/api/setup", {}));
    $("run-button").addEventListener("click", () => post("/api/runs", {}));
    $("seed-confirm").addEventListener("change", render);
    $("seed-button").addEventListener("click", () => {
      const body = seedRequest($("seed-confirm").checked);
      if (body) post("/api/setup/seed", body);
    });
    refresh();
    setInterval(refresh, 1000);
  })();
}
