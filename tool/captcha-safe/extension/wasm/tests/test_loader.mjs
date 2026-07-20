#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  CAPTCHA_SOLVER_CONTRACT,
  CaptchaSolverLoadError,
  instantiateCaptchaSolver,
} from "../loader/captcha-solver-loader.mjs";

const TARGET_WIDTH = 15;
const TARGET_HEIGHT = 13;
const BACKGROUND_WIDTH = 64;
const BACKGROUND_HEIGHT = 40;
const EXPECTED_LEFT = 27;
const EXPECTED_TOP = 12;
const TARGET_BYTES = TARGET_WIDTH * TARGET_HEIGHT * 3;
const BACKGROUND_BYTES = BACKGROUND_WIDTH * BACKGROUND_HEIGHT * 3;

const [wasmArgument, metadataArgument, nativeArgument] = process.argv.slice(2);
if (!wasmArgument || !metadataArgument || !nativeArgument) {
  throw new Error("usage: test_loader.mjs WASM BUILD_METADATA NATIVE_TEST");
}
const wasmPath = path.resolve(wasmArgument);
const metadataPath = path.resolve(metadataArgument);
const nativePath = path.resolve(nativeArgument);

function setRgb(buffer, width, x, y, value) {
  const offset = (y * width + x) * 3;
  buffer[offset] = value;
  buffer[offset + 1] = value;
  buffer[offset + 2] = value;
}

function fixture() {
  const target = new Uint8Array(TARGET_BYTES);
  const background = new Uint8Array(BACKGROUND_BYTES);
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
      const source = (y * TARGET_WIDTH + x) * 3;
      const destination = ((EXPECTED_TOP + y) * BACKGROUND_WIDTH + EXPECTED_LEFT + x) * 3;
      background.set(target.subarray(source, source + 3), destination);
    }
  }
  return { target, background };
}

function solve(instance, targetRgb, backgroundRgb) {
  return instance.solve({
    targetWidth: TARGET_WIDTH,
    targetHeight: TARGET_HEIGHT,
    backgroundWidth: BACKGROUND_WIDTH,
    backgroundHeight: BACKGROUND_HEIGHT,
    targetRgb,
    backgroundRgb,
  });
}

const wasmBytes = new Uint8Array(await readFile(wasmPath));
const metadata = JSON.parse(await readFile(metadataPath, "utf8"));
const digest = createHash("sha256").update(wasmBytes).digest("hex");
assert.equal(metadata.artifactSha256, digest);
assert.equal(metadata.solverReadiness, "PENDING");
assert.equal(metadata.algorithmId, CAPTCHA_SOLVER_CONTRACT.algorithmId);
assert.equal(metadata.containsOpenCv, false);
assert.equal(metadata.containsImageCodecs, false);

const instance = await instantiateCaptchaSolver({
  wasmBytes,
  expectedSha256: digest,
  cryptoProvider: webcrypto,
});
assert.equal(instance.solverReadiness, "PENDING");
assert.equal(instance.actionAuthorized, false);
assert.equal(instance.opencvParity, false);
assert.equal("drag" in instance, false);

const { target, background } = fixture();
const solved = solve(instance, target, background);
assert.equal(solved.actionAuthorized, false);
assert.equal(solved.opencvParity, false);
assert.equal(solved.result.decision, 1);
assert.equal(solved.result.reason, 0);
assert.equal(solved.result.left, EXPECTED_LEFT);
assert.equal(solved.result.top, EXPECTED_TOP);
assert.ok(Object.isFrozen(solved));
assert.ok(Object.isFrozen(solved.result));

const nativeOutput = execFileSync(nativePath, { encoding: "utf8" });
const vectorLine = nativeOutput
  .split("\n")
  .find((line) => line.startsWith("NATIVE_VECTOR_JSON "));
assert.ok(vectorLine, "native fixture did not emit its consistency vector");
const nativeResult = JSON.parse(vectorLine.slice("NATIVE_VECTOR_JSON ".length));
assert.deepEqual(solved.result, nativeResult, "native and WASM ABI results diverged");

const flatTarget = new Uint8Array(TARGET_BYTES).fill(128);
const flatBackground = new Uint8Array(BACKGROUND_BYTES).fill(128);
const abstained = solve(instance, flatTarget, flatBackground);
assert.equal(abstained.result.decision, 2);
assert.equal(abstained.result.reason, 1);
assert.equal(abstained.actionAuthorized, false);

assert.throws(
  () => solve(instance, target.subarray(1), background),
  (error) => error instanceof CaptchaSolverLoadError && error.code === "INPUT_INVALID",
);
await assert.rejects(
  instantiateCaptchaSolver({
    wasmBytes,
    expectedSha256: "0".repeat(64),
    cryptoProvider: webcrypto,
  }),
  (error) => error instanceof CaptchaSolverLoadError && error.code === "DIGEST_MISMATCH",
);

console.log(
  `loader/native/WASM consistency passed: sha256=${digest} ` +
    `center=(${solved.result.centerX},${solved.result.centerY}) actionAuthorized=false`,
);
