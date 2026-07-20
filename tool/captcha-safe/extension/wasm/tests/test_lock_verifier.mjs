#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const verifier = path.resolve(here, "../scripts/verify-formal-lock.mjs");
const realLockPath = path.resolve(here, "../toolchain-lock.json");
const realRaw = await readFile(realLockPath, "utf8");
const realLock = JSON.parse(realRaw);
const tempRoot = await mkdtemp(path.join(os.tmpdir(), "captcha-safe-lock-test-"));

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

function canonical(value) {
  return `${JSON.stringify(sorted(value), null, 2)}\n`;
}

async function rejected(name, contents, messagePattern) {
  const candidate = path.join(tempRoot, `${name}.json`);
  await writeFile(candidate, contents);
  const result = spawnSync(process.execPath, [verifier, candidate], {
    encoding: "utf8",
    timeout: 10_000,
  });
  assert.equal(result.status, 78, `${name} returned ${result.status}: ${result.stderr}`);
  assert.match(result.stderr, messagePattern, `${name} failed for the wrong reason`);
}

try {
  await rejected("pending", realRaw, /solverReadiness is not VERIFIED/);
  await rejected("noncanonical", `${realRaw}\n`, /not canonical sorted JSON/);
  await rejected(
    "duplicate",
    realRaw.replace('  "schemaVersion": 1,', '  "schemaVersion": 1,\n  "schemaVersion": 1,'),
    /not canonical sorted JSON/,
  );

  const unknown = structuredClone(realLock);
  unknown.unreviewedField = true;
  await rejected("unknown", canonical(unknown), /lock contains missing or unknown fields/);

  const llvmMissing = structuredClone(realLock);
  delete llvmMissing.llvmWasm.target;
  await rejected(
    "llvm-missing",
    canonical(llvmMissing),
    /llvmWasm contains missing or unknown fields/,
  );

  const sourceDigestTampered = structuredClone(realLock);
  sourceDigestTampered.minimalCore.sourceSha256 = "0".repeat(64);
  await rejected(
    "source-digest-tampered",
    canonical(sourceDigestTampered),
    /sourceSha256 does not bind the checked-in solver source/,
  );

  const headerDigestTampered = structuredClone(realLock);
  headerDigestTampered.minimalCore.headerSha256 = "f".repeat(64);
  await rejected(
    "header-digest-tampered",
    canonical(headerDigestTampered),
    /headerSha256 does not bind the checked-in ABI header/,
  );

  await rejected(
    "invalid-utf8",
    Buffer.from([0xff, 0xfe, 0xfd]),
    /encoded data was not valid|not valid for encoding/i,
  );
} finally {
  await rm(tempRoot, { recursive: true, force: true });
}

console.log("formal lock strict-parser tests passed");
