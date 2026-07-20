import assert from "node:assert/strict";
import test from "node:test";

import { createSingleFlight } from "../src/run-coordinator.js";
import { settleWithin, SolverRunError } from "../src/solve-runner.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

test("concurrent solve requests share one in-flight result instead of returning RUN_BUSY", async () => {
  const active = deferred();
  let runCount = 0;
  const runSingleFlight = createSingleFlight(() => {
    runCount += 1;
    return active.promise;
  });

  const first = runSingleFlight();
  const second = runSingleFlight();
  assert.strictEqual(second, first);
  assert.equal(runCount, 0, "the runner starts on the next microtask");

  await Promise.resolve();
  assert.equal(runCount, 1);
  active.resolve("solved");
  assert.equal(await first, "solved");
  assert.equal(await second, "solved");
});

test("success and rejection both release the single-flight slot", async () => {
  const first = deferred();
  let runCount = 0;
  const runSingleFlight = createSingleFlight(() => {
    runCount += 1;
    if (runCount === 1) return first.promise;
    if (runCount === 2) return "second result";
    return "third result";
  });

  const rejected = runSingleFlight();
  first.reject(Object.assign(new Error("solve timed out"), { code: "SOLVE_TIMEOUT" }));
  await assert.rejects(rejected, (error) => error.code === "SOLVE_TIMEOUT");
  assert.equal(await runSingleFlight(), "second result");
  assert.equal(await runSingleFlight(), "third result");
  assert.equal(runCount, 3);
});

test("keyed single-flight keeps different API keywords independent", async () => {
  const runs = [];
  const runSingleFlight = createSingleFlight(
    async (keyword) => {
      runs.push(keyword);
      return keyword;
    },
    (keyword) => keyword,
  );
  const firstA = runSingleFlight("单位A");
  const secondA = runSingleFlight("单位A");
  const firstB = runSingleFlight("单位B");
  assert.strictEqual(firstA, secondA);
  assert.notStrictEqual(firstA, firstB);
  assert.deepEqual(await Promise.all([firstA, secondA, firstB]), ["单位A", "单位A", "单位B"]);
  assert.deepEqual(runs, ["单位A", "单位B"]);
});

test("an offscreen timeout releases single-flight and permits immediate recovery", async () => {
  let runCount = 0;
  const never = new Promise(() => {});
  const runSingleFlight = createSingleFlight(() => {
    runCount += 1;
    if (runCount === 1) {
      return settleWithin(
        never,
        10,
        "OPENCV_UNAVAILABLE",
        "the local OpenCV solve did not finish in time",
      );
    }
    return "recovered";
  });

  const timedOut = runSingleFlight();
  assert.strictEqual(runSingleFlight(), timedOut);
  await assert.rejects(
    timedOut,
    (error) => error instanceof SolverRunError &&
      error.code === "OPENCV_UNAVAILABLE" &&
      error.message === "the local OpenCV solve did not finish in time",
  );
  assert.equal(await runSingleFlight(), "recovered");
  assert.equal(runCount, 2);
});

test("a fresh coordinator does not inherit an abandoned service-worker run", async () => {
  const abandoned = deferred();
  const oldCoordinator = createSingleFlight(() => abandoned.promise);
  const oldRun = oldCoordinator();

  let freshRunCount = 0;
  const freshCoordinator = createSingleFlight(() => {
    freshRunCount += 1;
    return "fresh result";
  });
  assert.equal(await freshCoordinator(), "fresh result");
  assert.equal(freshRunCount, 1);

  abandoned.resolve("old result");
  assert.equal(await oldRun, "old result");
});

test("createSingleFlight rejects a non-function runner", () => {
  assert.throws(() => createSingleFlight(null), /runner must be a function/u);
});
