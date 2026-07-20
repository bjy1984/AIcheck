import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import {
  assertCdpMethodAllowed,
  chromeLaunchArguments,
  hostContract,
  parseArguments,
  sanitizedChromeEnvironment,
  SMOKE_ASSERTION_NAMES,
  validateBrowserWebSocketUrl,
  validateSmokeReport,
} from "../../scripts/chrome_extension_smoke.mjs";

const extensionId = "bllipfmjmddgmgaabfmfhlkgbdhdiepe";

function reportFixture(platform = "darwin", architecture = "arm64") {
  return {
    schemaVersion: 2,
    status: "PASS",
    scope: "OPENCV_CNSE_SITE_EXTENSION_LOAD_ONLY",
    actionExecuted: false,
    externalNavigationExecuted: false,
    assertions: SMOKE_ASSERTION_NAMES.map((name) => ({
      name,
      passed: true,
    })),
    extension: {
      id: extensionId,
      version: "0.3.0",
      installType: "development",
      buildStatus: "OPENCV_CNSE_SITE",
      solveEnabled: true,
      algorithm: "opencv-edge-template-v1",
      opencvVersion: "4.13.0",
      externalTargetsAllowed: false,
    },
    runtime: {
      browserProduct: "HeadlessChrome/151.0.7922.34",
      protocolVersion: "1.3",
      platform,
      architecture,
      supportContract: hostContract(platform, architecture),
    },
    cdpProbe: {
      transport: "loopback-browser-devtools",
      commandSummary: [{ count: 1, method: "Browser.getVersion" }],
      inputCommandCount: 0,
      networkCommandCount: 0,
      pageNavigationCommandCount: 0,
      extensionDebuggerApiAvailable: true,
      extensionDebuggerAttached: false,
    },
    redaction: {
      urlsRetained: false,
      imageBytesRetained: false,
      credentialsRetained: false,
    },
    limitations: [
      "The extension load probe does not press the popup trigger, run OpenCV, or dispatch input.",
      "The probe opens only local, extension-owned browser targets.",
      "The probe is intentionally not an operating-system egress audit.",
      "The probe validates local loading and static contracts only, not recognition or drag geometry.",
    ],
  };
}

test("smoke host contracts cover exactly the three first-release platforms", () => {
  assert.equal(hostContract("darwin", "arm64"), "mac-arm64");
  assert.equal(hostContract("win32", "x64"), "win-x86_64");
  assert.equal(hostContract("linux", "x64"), "linux-x86_64");
  for (const unsupported of [
    ["darwin", "x64"],
    ["linux", "arm64"],
    ["win32", "ia32"],
    ["freebsd", "x64"],
  ]) {
    assert.throws(() => hostContract(...unsupported), /outside the three-platform/);
  }
});

test("smoke CLI binds version, host, ID, and an out-of-tree report", () => {
  const extensionRoot = resolve("extension");
  const output = resolve(extensionRoot, "..", "..", "smoke-report.json");
  const argv = [
    "--chrome", resolve("fake-chrome"),
    "--extension-root", extensionRoot,
    "--expected-id", extensionId,
    "--expected-version", "151.0.7922.34",
    "--expected-platform", "darwin",
    "--expected-arch", "arm64",
    "--output", output,
  ];
  const parsed = parseArguments(argv);
  assert.equal(parsed.expectedHostContract, "mac-arm64");
  assert.equal(parsed.output, output);
  assert.throws(
    () => parseArguments([...argv.slice(0, -1), resolve(extensionRoot, "report.json")]),
    /outside the source root/,
  );
  assert.throws(
    () => parseArguments([...argv, "--expected-arch", "arm64"]),
    /duplicate argument|all smoke-test arguments/,
  );
});

test("load-only CDP allowlist rejects input, network, and navigation methods", () => {
  for (const allowed of [
    "Browser.close",
    "Browser.getVersion",
    "Runtime.evaluate",
    "Target.attachToTarget",
    "Target.createTarget",
    "Target.detachFromTarget",
    "Target.getTargets",
  ]) {
    assert.equal(assertCdpMethodAllowed(allowed), true);
  }
  for (const forbidden of [
    "Input.dispatchMouseEvent",
    "Input.dispatchTouchEvent",
    "Network.enable",
    "Fetch.enable",
    "Page.navigate",
  ]) {
    assert.throws(() => assertCdpMethodAllowed(forbidden), /outside the load-only allowlist|forbidden/);
  }
});

test("popup evaluation is DOM-only and extension API contracts run in the service worker", async () => {
  const source = await readFile(
    new URL("../../scripts/chrome_extension_smoke.mjs", import.meta.url),
    "utf8",
  );
  const pageEvaluator = source.slice(
    source.indexOf("async function evaluateExtensionPage"),
    source.indexOf("async function evaluateServiceWorker"),
  );
  const workerEvaluator = source.slice(
    source.indexOf("async function evaluateServiceWorker"),
    source.indexOf("export function chromeLaunchArguments"),
  );

  assert.doesNotMatch(pageEvaluator, /chrome\.(?:runtime|debugger|storage)/u);
  assert.match(pageEvaluator, /documentReady/u);
  assert.match(pageEvaluator, /popupTriggerPresent/u);
  assert.match(workerEvaluator, /chrome\.runtime\.getManifest/u);
  assert.match(workerEvaluator, /vendor\/opencv\/lock\.json/u);
  assert.match(workerEvaluator, /debuggerPermissionAbsent/u);
  assert.doesNotMatch(workerEvaluator, /chrome\.debugger/u);
});

test("DevTools WebSocket must remain on the exact loopback port", () => {
  const valid = "ws://127.0.0.1:9222/devtools/browser/12345678-abcd-1234-abcd-123456789abc";
  assert.equal(validateBrowserWebSocketUrl(valid, 9222), valid);
  assert.equal(
    validateBrowserWebSocketUrl(
      "ws://localhost:9222/devtools/browser/12345678-abcd-1234-abcd-123456789abc",
      9222,
    ),
    valid,
  );
  for (const invalid of [
    "ws://127.0.0.1:9223/devtools/browser/12345678-abcd",
    "ws://192.0.2.1:9222/devtools/browser/12345678-abcd",
    "wss://127.0.0.1:9222/devtools/browser/12345678-abcd",
    "ws://127.0.0.1:9222/devtools/browser/12345678-abcd?token=secret",
  ]) {
    assert.throws(() => validateBrowserWebSocketUrl(invalid, 9222), /loopback binding/);
  }
});

test("Chrome child receives a minimal environment without CI credentials or injection variables", () => {
  const environment = sanitizedChromeEnvironment(
    {
      PATH: "/safe/bin",
      LANG: "C.UTF-8",
      SystemRoot: "C:\\Windows",
      GITHUB_TOKEN: "<redacted-fixture>",
      ACTIONS_ID_TOKEN_REQUEST_TOKEN: "<redacted-fixture>",
      AWS_SECRET_ACCESS_KEY: "<redacted-fixture>",
      DYLD_INSERT_LIBRARIES: "/malicious.dylib",
      NODE_OPTIONS: "--require malicious.js",
    },
    join(tmpdir(), "captcha-safe-smoke-contract"),
    "win32",
  );
  assert.equal(environment.PATH, "/safe/bin");
  assert.equal(environment.SystemRoot, "C:\\Windows");
  assert.equal(Object.hasOwn(environment, "GITHUB_TOKEN"), false);
  assert.equal(Object.hasOwn(environment, "ACTIONS_ID_TOKEN_REQUEST_TOKEN"), false);
  assert.equal(Object.hasOwn(environment, "AWS_SECRET_ACCESS_KEY"), false);
  assert.equal(Object.hasOwn(environment, "DYLD_INSERT_LIBRARIES"), false);
  assert.equal(Object.hasOwn(environment, "NODE_OPTIONS"), false);
  assert.match(environment.USERPROFILE, /captcha-safe-smoke-contract/u);
});

test("Chrome launch is extension-only, background-disabled, and has no external destination", () => {
  const arguments_ = chromeLaunchArguments(resolve("extension"), resolve("profile"));
  assert.equal(arguments_.at(-1), "about:blank");
  assert.equal(arguments_.includes("--disable-background-networking"), true);
  assert.equal(arguments_.includes("--host-resolver-rules=MAP * ~NOTFOUND"), true);
  assert.equal(arguments_.some((value) => /^https?:\/\//u.test(value)), false);
  assert.equal(arguments_.some((value) => value.startsWith("--load-extension=")), true);
  assert.equal(arguments_.some((value) => /Input\.|dispatchMouse|dispatchTouch/u.test(value)), false);
});

test("smoke reports are exact, redacted, action-free platform contracts", () => {
  for (const [platform, architecture] of [
    ["darwin", "arm64"],
    ["win32", "x64"],
    ["linux", "x64"],
  ]) {
    const report = reportFixture(platform, architecture);
    assert.equal(validateSmokeReport(report), report);
  }
  assert.throws(
    () => validateSmokeReport({ ...reportFixture(), actionExecuted: true }),
    /status or scope/,
  );
  assert.throws(
    () => validateSmokeReport({ ...reportFixture(), token: "secret" }),
    /fields are not exact/,
  );
  assert.throws(
    () => validateSmokeReport({
      ...reportFixture(),
      limitations: [
        "The extension load probe does not press the popup trigger, run OpenCV, or dispatch input.",
        "The probe opens an https://example.invalid external origin.",
        "The probe is intentionally not an operating-system egress audit.",
        "The probe validates local loading and static contracts only, not recognition or drag geometry.",
      ],
    }),
    /retained a URL/,
  );
});
