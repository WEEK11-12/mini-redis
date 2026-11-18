// TC-07-I-017 (screen logic): pure view decisions of examples/live_benchmark_ui.js.
// Run: node --test tests/live_benchmark_ui.test.js  (also invoked by tests/test_live_benchmark.py)
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const ui = require("../examples/live_benchmark_ui.js");

const CONDITIONS = ["no_cache", "miss", "hit"];

function setup(state, extra = {}) {
  return { state, step: null, message: "m", error: null, active_job: null, last_run_id: null,
           resources: {}, ...extra };
}

function result() {
  const conditions = {};
  CONDITIONS.forEach((c, i) => {
    conditions[c] = { median_ms: 1.5 + i, p90_ms: 2.5 + i, successes: 100, failures: 0 };
  });
  return {
    conditions,
    method: { warmup_per_condition: 5, rounds: 100, timer: "t", percentile: "p", key_seed: 1, key_space: 9 },
    environment: { python: "3", platform: "mac", machine: "arm64", commit: "c", sources_sha256: {},
                   mongo_before: { count: 1000001, cache_max_bytes: 268435456 }, mongo_after: {},
                   mongo_after_unavailable: false, runner: { image_id: "sha256:img" } },
  };
}

function run(state, extra = {}) {
  return { run_id: "20261119T000000Z-0123456789abcdef", state, step: null, error: null,
           result: null, partial: null, artifacts: { dir: "var/live-benchmark/runs/x", files: {} }, ...extra };
}

test("controls follow state: ready / seed_required / not_ready / failed", () => {
  assert.deepEqual(ui.controls(setup("ready")), { setup: true, seed: false, run: true });
  assert.deepEqual(ui.controls(setup("seed_required")), { setup: true, seed: true, run: false });
  assert.deepEqual(ui.controls(setup("not_ready")), { setup: true, seed: false, run: false });
  assert.deepEqual(ui.controls(setup("failed")), { setup: true, seed: false, run: false });
});

test("no new work while busy, preparing, blocked or in an unknown state", () => {
  const none = { setup: false, seed: false, run: false };
  assert.deepEqual(ui.controls(setup("ready", { active_job: { kind: "run", run_id: "r" } })), none);
  assert.deepEqual(ui.controls(setup("preparing")), none);
  assert.deepEqual(ui.controls(setup("recovery_required")), none);
  assert.deepEqual(ui.controls(setup("something_new")), none);
  assert.deepEqual(ui.controls(null), none);
});

test("recovery_required wins over a run record still saying running/preparing", () => {
  const blocked = setup("recovery_required", { error: { code: "RECOVERY_REQUIRED", message: "x" } });
  for (const state of ["running", "preparing"]) {
    const b = ui.banner(blocked, run(state));
    assert.equal(b.state, "recovery_required");
    assert.match(b.guide, /--recover/);
    const view = ui.runView(run(state), blocked);
    assert.equal(view.kind, "stale");
    assert.equal(view.rows, undefined);
  }
});

test("an unfinished run without a matching active job is not shown as in progress", () => {
  const view = ui.runView(run("running"), setup("ready"));
  assert.equal(view.kind, "stale");
  const live = ui.runView(run("running", { step: "running_benchmark" }),
                          setup("ready", { active_job: { kind: "run", run_id: run("x").run_id } }));
  assert.equal(live.kind, "progress");
  assert.equal(live.step, ui.stepLabel("running_benchmark"));
  assert.ok(!/%/.test(JSON.stringify(live)), "no percentage progress");
});

test("success shows only this run's validated conditions", () => {
  const view = ui.runView(run("succeeded", { result: result() }), setup("ready"));
  assert.equal(view.kind, "success");
  assert.deepEqual(view.rows.map((r) => r.condition), CONDITIONS);
  assert.deepEqual(view.rows[1], { condition: "miss", median_ms: 2.5, p90_ms: 3.5, successes: 100, failures: 0 });
  assert.equal(view.mongoAfterUnavailable, false);
});

test("a succeeded record whose result is not well formed is never drawn", () => {
  const broken = [
    (r) => delete r.conditions.hit,
    (r) => { r.conditions.miss.median_ms = NaN; },
    (r) => { r.conditions.miss.p90_ms = -1; },
    (r) => { r.conditions.miss.median_ms = true; },
    (r) => { r.conditions.no_cache.successes = 99; },
    (r) => { r.conditions.no_cache.failures = 1; },
    (r) => { r.conditions.no_cache.successes = 100.5; },
    (r) => { r.conditions.extra = r.conditions.hit; },
    (r) => delete r.method,
    (r) => delete r.environment,
  ];
  for (const mutate of broken) {
    const r = result();
    mutate(r);
    const view = ui.runView(run("succeeded", { result: r }), setup("ready"));
    assert.equal(view.kind, "invalid", String(mutate));
    assert.equal(view.rows, undefined);
  }
  assert.equal(ui.runView(run("succeeded", { result: null }), setup("ready")).kind, "invalid");
});

test("failures and timeouts show counts only from partial, never as a comparison", () => {
  const partial = { aborted: "KeyboardInterrupt: ",
                    conditions: { no_cache: { successes: 3, failures: 0 }, miss: { successes: 2, failures: 1 },
                                  hit: { successes: 0, failures: 0 } } };
  for (const state of ["failed", "timed_out"]) {
    const view = ui.runView(run(state, { error: { code: "TIMED_OUT", message: "m" }, partial,
                                         result: result() }), setup("ready"));
    assert.equal(view.kind, "failure");
    assert.equal(view.rows, undefined);
    assert.deepEqual(view.partialRows[1], { condition: "miss", successes: 2, failures: 1 });
    assert.equal(view.aborted, "KeyboardInterrupt: ");
  }
  const none = ui.runView(run("failed", { error: { code: "BENCHMARK_FAILED", message: "m" } }), setup("ready"));
  assert.equal(none.partialRows, null);
  const bad = ui.runView(run("failed", { error: { code: "X", message: "m" },
                                         partial: { aborted: null, conditions: { hit: { successes: "1" } } } }),
                         setup("ready"));
  assert.equal(bad.partialRows, null);
});

test("every contract error code has specific guidance; unknown codes stay generic", () => {
  const codes = ["BUSY", "NOT_READY", "SEED_NOT_REQUIRED", "CONFIRMATION_REQUIRED", "RECOVERY_REQUIRED",
                 "RECORD_UNAVAILABLE", "FORBIDDEN_REQUEST", "RESOURCE_CONFLICT", "RESOURCE_MISMATCH",
                 "PORT_CONFLICT", "DOCKER_UNAVAILABLE", "IMAGE_PULL_FAILED", "CONTAINER_START_FAILED",
                 "MONGO_NOT_READY", "SEED_CHECK_FAILED", "MEASUREMENT_CONDITION_UNMET", "SEED_FAILED",
                 "SEED_TIMEOUT", "SEED_REQUIRED", "SEED_MISMATCH", "RESTART_FAILED", "BENCHMARK_FAILED",
                 "RESULT_INVALID", "TIMED_OUT", "SERVER_STOPPED", "SERVER_INTERRUPTED", "INTERNAL_ERROR",
                 "SHARED_RECORD_MISSING", "SHARED_RECORD_UNVERIFIED", "SHARED_RECORD_UNREADABLE",
                 "RUN_NOT_FOUND"];
  const generic = ui.guideFor("NO_SUCH_CODE");
  for (const code of codes) {
    assert.notEqual(ui.guideFor(code), generic, code);
    assert.doesNotMatch(ui.guideFor(code), /자동(으로)? (삭제|정리)합니다|docker (rm|volume rm)/, code);
  }
  assert.match(ui.guideFor("RESOURCE_MISMATCH"), /자동으로 다시 만들지 않/);
  assert.match(ui.guideFor("MEASUREMENT_CONDITION_UNMET"), /시드 재생성/);
});

test("blocked shared-record states keep their own guidance instead of --recover", () => {
  // --recover cannot settle these: the shared record is absent, unverifiable or unreadable
  for (const code of ["SHARED_RECORD_MISSING", "SHARED_RECORD_UNVERIFIED", "SHARED_RECORD_UNREADABLE"]) {
    const b = ui.banner(setup("recovery_required", { error: { code, message: "server text" } }));
    assert.equal(b.state, "recovery_required", code);
    assert.equal(b.guide, ui.guideFor(code), code);
    assert.doesNotMatch(b.guide, /--recover/, code);
    assert.deepEqual(ui.controls(setup("recovery_required", { error: { code } })),
                     { setup: false, seed: false, run: false });
  }
  assert.match(ui.guideFor("SHARED_RECORD_UNVERIFIED"), /서버를 다시 시작/);
  for (const code of ["RECOVERY_REQUIRED", "RECORD_UNAVAILABLE", undefined]) {
    const b = ui.banner(setup("recovery_required", { error: code ? { code, message: "m" } : null }));
    assert.match(b.guide, /--recover/, String(code));
  }
});

function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

test("a poll tick is skipped while the previous refresh is still in flight", async () => {
  const pending = [];
  const applied = [];
  const poller = ui.createPoller(() => { const d = deferred(); pending.push(d); return d.promise; },
                                 (state) => applied.push(state));
  const first = poller.tick();
  assert.equal(await poller.tick(), "skipped");
  assert.equal(pending.length, 1);
  pending[0].resolve("A");
  assert.equal(await first, "applied");
  assert.deepEqual(applied, ["A"]);
  poller.tick();
  assert.equal(pending.length, 2);
});

test("a late, older response never overwrites a newer one", async () => {
  const pending = [];
  const applied = [];
  const poller = ui.createPoller(() => { const d = deferred(); pending.push(d); return d.promise; },
                                 (state) => applied.push(state));
  const older = poller.tick();                      // regular poll, slow
  const newer = poller.tick({ force: true });       // refresh right after a POST
  assert.equal(pending.length, 2);
  pending[1].resolve("new");
  assert.equal(await newer, "applied");
  pending[0].resolve("old");
  assert.equal(await older, "stale");
  assert.deepEqual(applied, ["new"]);
  const next = poller.tick();  // nothing in flight any more: a regular tick runs again
  assert.equal(pending.length, 3);
  pending[2].resolve("next");
  assert.equal(await next, "applied");
  assert.deepEqual(applied, ["new", "next"]);
});

test("seed request is only possible with the explicit confirmation", () => {
  assert.equal(ui.seedRequest(false), null);
  assert.deepEqual(ui.seedRequest(true), { confirm_replace: true });
});
