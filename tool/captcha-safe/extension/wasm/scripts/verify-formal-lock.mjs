#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const defaultLockPath = path.resolve(here, "../toolchain-lock.json");
const lockPath = path.resolve(process.argv[2] ?? defaultLockPath);
const solverRoot = path.resolve(here, "..");
const sha256 = /^[a-f0-9]{64}$/;

async function fileDigest(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function sorted(value) {
  if (Array.isArray(value)) {
    return value.map(sorted);
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sorted(value[key])]),
    );
  }
  return value;
}

function exactKeys(value, expected, label) {
  assert.ok(value !== null && typeof value === "object" && !Array.isArray(value),
    `${label} must be an object`);
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(),
    `${label} contains missing or unknown fields`);
}

function pendingOrDigest(value, label) {
  assert.equal(typeof value, "string", `${label} must be text`);
  assert.ok(value === "PENDING" || sha256.test(value), `${label} must be PENDING or SHA-256`);
}

function pendingOrVersion(value, label) {
  assert.equal(typeof value, "string", `${label} must be text`);
  assert.ok(value === "PENDING" || /^[0-9]+(?:\.[0-9]+){1,3}$/.test(value),
    `${label} must be PENDING or a numeric pinned version`);
}

function verifiedVersion(component, label) {
  assert.equal(typeof component.version, "string", `${label}.version must be text`);
  assert.notEqual(component.version, "PENDING", `${label}.version is PENDING`);
  assert.ok(component.version.length > 0, `${label}.version is empty`);
}

function verifiedDigest(value, label) {
  assert.equal(typeof value, "string", `${label} must be text`);
  assert.match(value, sha256, `${label} is not a verified SHA-256 digest`);
}

try {
  const rawBytes = await readFile(lockPath);
  const raw = new TextDecoder("utf-8", { fatal: true }).decode(rawBytes);
  const lock = JSON.parse(raw);
  const canonical = `${JSON.stringify(sorted(lock), null, 2)}\n`;
  assert.equal(
    raw,
    canonical,
    "lock is not canonical sorted JSON (duplicate keys, key order, or whitespace changed)",
  );

  exactKeys(lock, [
    "codecs",
    "emscripten",
    "formalBuildAllowed",
    "llvmWasm",
    "minimalCore",
    "notes",
    "opencv",
    "schemaVersion",
    "solverAbiVersion",
    "solverReadiness",
  ], "lock");
  exactKeys(lock.minimalCore, [
    "algorithmId", "artifactSha256", "headerSha256", "language", "sourceSha256",
  ], "minimalCore");
  exactKeys(lock.llvmWasm, ["executableSha256", "target", "version"], "llvmWasm");
  exactKeys(lock.emscripten, ["sdkManifestSha256", "target", "version"], "emscripten");
  exactKeys(lock.opencv, ["integrationStatus", "sourceArchiveSha256", "version"], "opencv");
  exactKeys(lock.codecs, ["libjpegTurbo", "libpng", "libwebp"], "codecs");
  for (const [name, codec] of Object.entries(lock.codecs)) {
    exactKeys(codec, ["integrationStatus", "sourceArchiveSha256", "version"], `codecs.${name}`);
  }

  assert.equal(lock.schemaVersion, 1, "unsupported lock schema");
  assert.equal(lock.solverAbiVersion, 1, "unsupported solver ABI");
  assert.equal(lock.minimalCore.language, "C11");
  assert.equal(lock.minimalCore.algorithmId, "captcha-safe-canny-like-ncc-v1");
  pendingOrDigest(lock.minimalCore.sourceSha256, "minimalCore.sourceSha256");
  pendingOrDigest(lock.minimalCore.headerSha256, "minimalCore.headerSha256");
  pendingOrDigest(lock.minimalCore.artifactSha256, "minimalCore.artifactSha256");
  assert.equal(
    lock.minimalCore.sourceSha256,
    await fileDigest(path.join(solverRoot, "src/captcha_solver.c")),
    "minimalCore.sourceSha256 does not bind the checked-in solver source",
  );
  assert.equal(
    lock.minimalCore.headerSha256,
    await fileDigest(path.join(solverRoot, "include/captcha_solver.h")),
    "minimalCore.headerSha256 does not bind the checked-in ABI header",
  );
  pendingOrVersion(lock.llvmWasm.version, "llvmWasm.version");
  pendingOrDigest(lock.llvmWasm.executableSha256, "llvmWasm.executableSha256");
  assert.equal(lock.llvmWasm.target, "wasm32-unknown-unknown");
  pendingOrVersion(lock.emscripten.version, "emscripten.version");
  pendingOrDigest(lock.emscripten.sdkManifestSha256, "emscripten.sdkManifestSha256");
  assert.equal(lock.emscripten.target, "wasm32-unknown-emscripten");
  assert.equal(lock.opencv.version, "5.0.0");
  pendingOrDigest(lock.opencv.sourceArchiveSha256, "opencv.sourceArchiveSha256");
  assert.ok(["NOT_BUILT", "BUILT_VERIFIED"].includes(lock.opencv.integrationStatus));
  for (const [name, codec] of Object.entries(lock.codecs)) {
    pendingOrVersion(codec.version, `codecs.${name}.version`);
    pendingOrDigest(codec.sourceArchiveSha256, `codecs.${name}.sourceArchiveSha256`);
    assert.ok(["NOT_BUILT", "BUILT_VERIFIED"].includes(codec.integrationStatus));
  }
  assert.ok(["PENDING", "VERIFIED"].includes(lock.solverReadiness));
  assert.equal(typeof lock.formalBuildAllowed, "boolean");
  assert.ok(Array.isArray(lock.notes) && lock.notes.every((note) => typeof note === "string"));
  if (lock.solverReadiness === "PENDING") {
    assert.equal(lock.formalBuildAllowed, false, "PENDING readiness cannot allow formal builds");
  }

  assert.equal(lock.solverReadiness, "VERIFIED", "solverReadiness is not VERIFIED");
  assert.equal(lock.formalBuildAllowed, true, "formalBuildAllowed is false");

  verifiedDigest(lock.minimalCore.sourceSha256, "minimalCore.sourceSha256");
  verifiedDigest(lock.minimalCore.headerSha256, "minimalCore.headerSha256");
  verifiedDigest(lock.minimalCore.artifactSha256, "minimalCore.artifactSha256");

  verifiedVersion(lock.emscripten, "emscripten");
  verifiedDigest(lock.emscripten.sdkManifestSha256, "emscripten.sdkManifestSha256");

  verifiedVersion(lock.llvmWasm, "llvmWasm");
  verifiedDigest(lock.llvmWasm.executableSha256, "llvmWasm.executableSha256");

  verifiedVersion(lock.opencv, "opencv");
  verifiedDigest(lock.opencv.sourceArchiveSha256, "opencv.sourceArchiveSha256");
  assert.equal(lock.opencv.integrationStatus, "BUILT_VERIFIED");

  for (const [name, codec] of Object.entries(lock.codecs)) {
    verifiedVersion(codec, `codecs.${name}`);
    verifiedDigest(codec.sourceArchiveSha256, `codecs.${name}.sourceArchiveSha256`);
    assert.equal(codec.integrationStatus, "BUILT_VERIFIED");
  }
} catch (error) {
  console.error(`formal WASM toolchain lock rejected: ${error.message}`);
  process.exit(78);
}

console.log("formal WASM toolchain lock is VERIFIED");
