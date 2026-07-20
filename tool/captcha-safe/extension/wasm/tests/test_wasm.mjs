#!/usr/bin/env node

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TARGET_WIDTH = 15;
const TARGET_HEIGHT = 13;
const BACKGROUND_WIDTH = 64;
const BACKGROUND_HEIGHT = 40;
const EXPECTED_LEFT = 27;
const EXPECTED_TOP = 12;
const TARGET_BYTES = TARGET_WIDTH * TARGET_HEIGHT * 3;
const BACKGROUND_BYTES = BACKGROUND_WIDTH * BACKGROUND_HEIGHT * 3;

const here = path.dirname(fileURLToPath(import.meta.url));
const defaultWasm = path.resolve(here, "../dist/captcha_solver.wasm");
const wasmPath = path.resolve(process.argv[2] ?? defaultWasm);

function exported(exports, name) {
  const value = exports[name] ?? exports[`_${name}`];
  assert.equal(typeof value, "function", `missing WASM export ${name}`);
  return value;
}

function setRgb(buffer, width, x, y, value) {
  const offset = (y * width + x) * 3;
  buffer[offset] = value;
  buffer[offset + 1] = value;
  buffer[offset + 2] = value;
}

function fillFixture(target, background) {
  target.fill(128);
  background.fill(128);
  for (let y = 1; y + 1 < TARGET_HEIGHT; y += 1) {
    for (let x = 1; x + 1 < TARGET_WIDTH; x += 1) {
      const mixed = x * 37 + y * 53 + x * y * 11 + (x ^ y) * 17;
      setRgb(target, TARGET_WIDTH, x, y, 24 + (mixed % 208));
    }
  }
  for (let y = 0; y < TARGET_HEIGHT; y += 1) {
    for (let x = 0; x < TARGET_WIDTH; x += 1) {
      const targetOffset = (y * TARGET_WIDTH + x) * 3;
      const backgroundOffset =
        ((EXPECTED_TOP + y) * BACKGROUND_WIDTH + EXPECTED_LEFT + x) * 3;
      background.set(target.subarray(targetOffset, targetOffset + 3), backgroundOffset);
    }
  }
}

function parseResult(memory, pointer) {
  const view = new DataView(memory.buffer, pointer, 112);
  return Object.freeze({
    abiVersion: view.getUint32(0, true),
    structSize: view.getUint32(4, true),
    decision: view.getUint32(8, true),
    reason: view.getUint32(12, true),
    centerX: view.getUint32(16, true),
    centerY: view.getUint32(20, true),
    left: view.getUint32(24, true),
    top: view.getUint32(28, true),
    confidenceQ30: view.getInt32(32, true),
    top1Q30: view.getInt32(36, true),
    top2Q30: view.getInt32(40, true),
    peakGapQ30: view.getUint32(44, true),
    peakSignificanceQ20: view.getUint32(48, true),
    targetTextureQ20: view.getUint32(52, true),
    backgroundTextureQ20: view.getUint32(56, true),
    targetEdgeDensityQ20: view.getUint32(60, true),
    backgroundEdgeDensityQ20: view.getUint32(64, true),
    localSharpnessQ20: view.getUint32(68, true),
    targetCannyEdgeCount: view.getUint32(72, true),
    backgroundCannyEdgeCount: view.getUint32(76, true),
    candidateCount: view.getUint32(80, true),
    nccWork: view.getUint32(84, true),
    targetWidth: view.getUint32(88, true),
    targetHeight: view.getUint32(92, true),
    backgroundWidth: view.getUint32(96, true),
    backgroundHeight: view.getUint32(100, true),
  });
}

const bytes = await readFile(wasmPath);
const imports = {
  env: Object.create(null),
  wasi_snapshot_preview1: Object.create(null),
};
const instantiated = await WebAssembly.instantiate(bytes, imports);
const exports = instantiated.instance.exports;
assert.ok(exports.memory instanceof WebAssembly.Memory, "WASM must export fixed linear memory");
assert.equal(exports.memory.buffer.byteLength, 16_777_216, "unexpected initial WASM memory");
assert.throws(
  () => exports.memory.grow(1),
  RangeError,
  "WASM memory unexpectedly permits growth",
);

const abiVersion = exported(exports, "solver_abi_version");
const configSize = exported(exports, "solver_config_size");
const resultSize = exported(exports, "solver_result_size");
const targetCapacity = exported(exports, "solver_target_rgb_capacity");
const backgroundCapacity = exported(exports, "solver_background_rgb_capacity");
const targetPointer = exported(exports, "solver_target_rgb");
const backgroundPointer = exported(exports, "solver_background_rgb");
const configPointer = exported(exports, "solver_config");
const resultPointer = exported(exports, "solver_result");
const reset = exported(exports, "solver_reset");
const solve = exported(exports, "solver_solve");
const solveFixture = () => solve(
  TARGET_WIDTH,
  TARGET_HEIGHT,
  BACKGROUND_WIDTH,
  BACKGROUND_HEIGHT,
  TARGET_BYTES,
  BACKGROUND_BYTES,
);

assert.equal(abiVersion(), 1);
assert.equal(configSize(), 56);
assert.equal(resultSize(), 112);
assert.equal(targetCapacity(), 196608);
assert.equal(backgroundCapacity(), 1572864);

reset();
const target = new Uint8Array(
  exports.memory.buffer,
  targetPointer(),
  TARGET_BYTES,
);
const background = new Uint8Array(
  exports.memory.buffer,
  backgroundPointer(),
  BACKGROUND_BYTES,
);
fillFixture(target, background);
assert.equal(solveFixture(), 0);
const first = parseResult(exports.memory, resultPointer());
assert.equal(first.abiVersion, 1);
assert.equal(first.structSize, 112);
assert.equal(first.decision, 1);
assert.equal(first.reason, 0);
assert.equal(first.left, EXPECTED_LEFT);
assert.equal(first.top, EXPECTED_TOP);
assert.equal(first.centerX, EXPECTED_LEFT + Math.floor(TARGET_WIDTH / 2));
assert.equal(first.centerY, EXPECTED_TOP + Math.floor(TARGET_HEIGHT / 2));
assert.ok(first.confidenceQ30 > 2 ** 29);
assert.ok(first.peakGapQ30 > 0);
assert.ok(first.nccWork > 0);

assert.equal(solveFixture(), 0);
assert.deepEqual(parseResult(exports.memory, resultPointer()), first);

reset();
target.fill(128);
background.fill(128);
assert.equal(solveFixture(), 0);
let result = parseResult(exports.memory, resultPointer());
assert.equal(result.decision, 2);
assert.equal(result.reason, 1);

reset();
fillFixture(target, background);
const config = new DataView(exports.memory.buffer, configPointer(), 56);
config.setUint32(12, config.getUint32(8, true), true);
assert.equal(solveFixture(), -2);
result = parseResult(exports.memory, resultPointer());
assert.equal(result.decision, 3);
assert.equal(result.reason, 101);

reset();
fillFixture(target, background);
new DataView(exports.memory.buffer, configPointer(), 56).setUint32(52, 1, true);
assert.equal(solveFixture(), -3);
result = parseResult(exports.memory, resultPointer());
assert.equal(result.decision, 3);
assert.equal(result.reason, 102);

reset();
fillFixture(target, background);
assert.equal(
  solve(
    TARGET_WIDTH,
    TARGET_HEIGHT,
    BACKGROUND_WIDTH,
    BACKGROUND_HEIGHT,
    TARGET_BYTES - 1,
    BACKGROUND_BYTES,
  ),
  -5,
);
result = parseResult(exports.memory, resultPointer());
assert.equal(result.decision, 3);
assert.equal(result.reason, 104);

console.log(
  `WASM solver tests passed: center=(${first.centerX},${first.centerY}) ` +
    `confidence_q30=${first.confidenceQ30} gap_q30=${first.peakGapQ30} ` +
    `significance_q20=${first.peakSignificanceQ20} work=${first.nccWork}`,
);
