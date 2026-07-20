import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("manifest limits the active-page helper to the CNSE public-search host", async () => {
  const manifest = JSON.parse(await readFile(new URL("manifest.json", root), "utf8"));
  const config = JSON.parse(await readFile(new URL("build-config.json", root), "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.incognito, "split");
  assert.deepEqual(manifest.host_permissions, ["https://cnse.e-cqs.cn/*"]);
  assert.deepEqual([...manifest.permissions].sort(), ["offscreen", "scripting", "tabs"]);
  assert.equal(
    manifest.content_security_policy.extension_pages,
    "script-src 'self' 'wasm-unsafe-eval'; object-src 'self';",
  );
  assert.equal(config.schemaVersion, 2);
  assert.equal(config.status, "OPENCV_CNSE_SITE");
  assert.equal(config.solveEnabled, true);
  assert.equal(config.algorithm, "opencv-edge-template-v1");
  assert.equal(config.opencvVersion, "4.13.0");
  assert.equal(config.externalTargetsAllowed, false);
  assert.equal(config.remoteCodeAllowed, false);
});

test("popup describes CNSE-only active-tab behavior", async () => {
  const html = await readFile(new URL("popup/popup.html", root), "utf8");
  const script = await readFile(new URL("popup/popup.js", root), "utf8");
  assert.match(html, /CNSE 纯 API 查询助手/u);
  assert.match(html, /cnse\.e-cqs\.cn/u);
  assert.match(html, /识别并查询/u);
  assert.match(html, /不导出 Cookie/u);
  assert.doesNotMatch(html, /run-self-test/u);
  assert.match(script, /request\("solve\.start", \{ keyword \}\)/u);
});

test("service worker validates messages and uses the active-page runner", async () => {
  const worker = await readFile(new URL("src/service-worker.js", root), "utf8");
  assert.match(worker, /validateLocalMessage\(request\)/u);
  assert.match(worker, /runCnseApiRecognition\(chrome, keyword\)/u);
  assert.match(worker, /createSingleFlight/u);
  assert.doesNotMatch(worker, /RUN_BUSY/u);
  assert.doesNotMatch(worker, /forced|bypass|UNLOCKED/iu);
});
