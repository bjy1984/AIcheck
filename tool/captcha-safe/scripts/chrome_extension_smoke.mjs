#!/usr/bin/env node
/** Load the local OpenCV CNSE-site extension in fixed Chrome without running a solve. */

import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const MAX_DIAGNOSTIC_BYTES = 64 * 1024;
const MAX_HTTP_BYTES = 1024 * 1024;
const START_TIMEOUT_MS = 20_000;
const COMMAND_TIMEOUT_MS = 10_000;
const EXTENSION_ID_RE = /^[a-p]{32}$/;
const ALLOWED_CDP_METHODS = new Set([
  "Browser.close",
  "Browser.getVersion",
  "Runtime.evaluate",
  "Target.attachToTarget",
  "Target.createTarget",
  "Target.detachFromTarget",
  "Target.getTargets",
]);
const HOST_CONTRACTS = new Map([
  ["darwin/arm64", "mac-arm64"],
  ["linux/x64", "linux-x86_64"],
  ["win32/x64", "win-x86_64"],
]);
export const SMOKE_ASSERTION_NAMES = Object.freeze([
  "host_platform_exact",
  "host_architecture_exact",
  "host_support_contract_exact",
  "extension_page_loaded",
  "service_worker_loaded",
  "runtime_extension_id_exact",
  "config_extension_id_exact",
  "manifest_v3",
  "minimum_chrome_120",
  "manifest_background_exact",
  "manifest_permissions_exact",
  "manifest_cnse_site_exact",
  "manifest_csp_exact",
  "config_contract_exact",
  "opencv_cnse_site_status",
  "solve_enabled",
  "solver_algorithm_exact",
  "opencv_version_exact",
  "external_targets_disabled",
  "remote_code_disabled",
  "opencv_vendor_artifact_present",
  "opencv_vendor_lock_present",
  "opencv_vendor_license_present",
  "opencv_vendor_lock_exact",
  "extension_debugger_permission_absent",
  "extension_storage_api_absent",
  "worker_runtime_id_exact",
  "worker_extension_origin",
  "worker_debugger_permission_absent",
  "worker_storage_api_absent",
  "cdp_input_commands_zero",
  "cdp_network_commands_zero",
  "cdp_page_navigation_commands_zero",
  "browser_version_exact",
]);

export class SmokeError extends Error {}

export function hostContract(platform, architecture) {
  const contract = HOST_CONTRACTS.get(`${platform}/${architecture}`);
  if (!contract) throw new SmokeError("smoke host is outside the three-platform support matrix");
  return contract;
}

export function parseArguments(argv) {
  const known = new Set([
    "--chrome",
    "--extension-root",
    "--expected-arch",
    "--expected-id",
    "--expected-platform",
    "--expected-version",
    "--output",
  ]);
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!known.has(flag) || typeof value !== "string" || value.length === 0) {
      throw new SmokeError(
        "usage: chrome_extension_smoke.mjs --chrome PATH --extension-root DIR " +
          "--expected-id ID --expected-version VERSION --expected-platform PLATFORM " +
          "--expected-arch ARCH --output PATH",
      );
    }
    if (values.has(flag)) throw new SmokeError(`duplicate argument: ${flag}`);
    values.set(flag, value);
  }
  if (values.size !== known.size) throw new SmokeError("all smoke-test arguments are required");
  const expectedId = values.get("--expected-id");
  if (!EXTENSION_ID_RE.test(expectedId)) throw new SmokeError("expected extension ID is invalid");
  const expectedVersion = values.get("--expected-version");
  if (!/^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/.test(expectedVersion)) {
    throw new SmokeError("expected Chrome version is invalid");
  }
  const expectedPlatform = values.get("--expected-platform");
  const expectedArchitecture = values.get("--expected-arch");
  const expectedHostContract = hostContract(expectedPlatform, expectedArchitecture);
  const extensionRoot = resolve(values.get("--extension-root"));
  const sourceRoot = resolve(extensionRoot, "..");
  const output = resolve(values.get("--output"));
  const outputRelative = relative(sourceRoot, output);
  if (
    outputRelative === "" ||
    (outputRelative !== ".." &&
      !outputRelative.startsWith(`..${sep}`) &&
      !isAbsolute(outputRelative))
  ) {
    throw new SmokeError("smoke report output must be outside the source root");
  }
  return Object.freeze({
    chrome: resolve(values.get("--chrome")),
    extensionRoot,
    expectedArchitecture,
    expectedHostContract,
    expectedId,
    expectedPlatform,
    expectedVersion,
    output,
  });
}

export function assertCdpMethodAllowed(method) {
  if (typeof method !== "string" || !ALLOWED_CDP_METHODS.has(method)) {
    throw new SmokeError(`CDP method is outside the load-only allowlist: ${String(method)}`);
  }
  if (method.startsWith("Input.") || method === "Page.navigate") {
    throw new SmokeError("action or page-navigation CDP commands are forbidden in load smoke");
  }
  return true;
}

export function validateBrowserWebSocketUrl(value, expectedPort) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new SmokeError("DevTools browser WebSocket URL is invalid");
  }
  if (
    parsed.protocol !== "ws:" ||
    (parsed.hostname !== "127.0.0.1" && parsed.hostname !== "localhost") ||
    parsed.port !== String(expectedPort) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash ||
    !/^\/devtools\/browser\/[A-Za-z0-9-]{8,128}$/u.test(parsed.pathname)
  ) {
    throw new SmokeError("DevTools browser WebSocket URL escaped the loopback binding");
  }
  // Chrome may advertise `localhost` even when bound to 127.0.0.1. Rewrite it
  // before connecting so the smoke probe never performs a DNS lookup.
  parsed.hostname = "127.0.0.1";
  return parsed.href;
}

export function sanitizedChromeEnvironment(source, temporaryRoot, platform) {
  const environment = {};
  for (const key of ["LANG", "LC_ALL", "PATH", "SystemRoot", "WINDIR"]) {
    if (typeof source?.[key] === "string" && source[key].length <= 8192) {
      environment[key] = source[key];
    }
  }
  const home = join(temporaryRoot, "home");
  const temporary = join(temporaryRoot, "tmp");
  environment.HOME = home;
  environment.TMPDIR = temporary;
  environment.TEMP = temporary;
  environment.TMP = temporary;
  if (platform === "win32") {
    environment.USERPROFILE = home;
    environment.APPDATA = join(home, "AppData", "Roaming");
    environment.LOCALAPPDATA = join(home, "AppData", "Local");
  }
  return Object.freeze(environment);
}

async function requireFile(path, label) {
  const info = await stat(path).catch(() => null);
  if (!info?.isFile()) throw new SmokeError(`${label} is not a regular file`);
}

async function requireDirectory(path, label) {
  const info = await stat(path).catch(() => null);
  if (!info?.isDirectory()) throw new SmokeError(`${label} is not a directory`);
}

function boundedDiagnostic(stream) {
  let value = "";
  stream?.setEncoding("utf8");
  stream?.on("data", (chunk) => {
    if (value.length < MAX_DIAGNOSTIC_BYTES) {
      value += chunk.slice(0, MAX_DIAGNOSTIC_BYTES - value.length);
    }
  });
  return () => value.replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, 2048);
}

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function readDevToolsPort(profile, child) {
  const path = join(profile, "DevToolsActivePort");
  const deadline = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.spawnFailure) throw new SmokeError("Chrome process could not be started");
    if (child.exitCode !== null) throw new SmokeError("Chrome exited before DevTools was ready");
    try {
      const info = await stat(path);
      if (!info.isFile() || info.size > 1024) {
        throw new SmokeError("DevToolsActivePort is not a bounded regular file");
      }
      if (info.size < 2) {
        await delay(50);
        continue;
      }
      const lines = (await readFile(path, "utf8")).trim().split(/\r?\n/u);
      if (/^[0-9]{2,5}$/.test(lines[0])) {
        const port = Number(lines[0]);
        if (port >= 1024 && port <= 65535) return port;
      }
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    await delay(50);
  }
  throw new SmokeError("Chrome did not expose a bounded DevTools endpoint");
}

async function boundedJson(url) {
  const response = await fetch(url, {
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(COMMAND_TIMEOUT_MS),
  });
  if (!response.ok) throw new SmokeError("DevTools HTTP endpoint failed");
  const declared = response.headers.get("content-length");
  if (declared && (!/^[0-9]+$/.test(declared) || Number(declared) > MAX_HTTP_BYTES)) {
    throw new SmokeError("DevTools HTTP response is oversized");
  }
  if (!response.body?.getReader) throw new SmokeError("DevTools HTTP response is not streamable");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    if (!(value instanceof Uint8Array)) throw new SmokeError("DevTools HTTP stream is invalid");
    size += value.byteLength;
    if (size > MAX_HTTP_BYTES) {
      await reader.cancel();
      throw new SmokeError("DevTools HTTP response is oversized");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new SmokeError("DevTools HTTP response is not UTF-8");
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new SmokeError("DevTools HTTP response is not JSON");
  }
}

class CdpClient {
  constructor(url) {
    this.url = url;
    this.socket = null;
    this.nextId = 1;
    this.pending = new Map();
    this.methodCounts = new Map();
  }

  async connect() {
    this.socket = new WebSocket(this.url);
    await new Promise((resolveOpen, rejectOpen) => {
      const timer = setTimeout(() => rejectOpen(new SmokeError("CDP WebSocket timed out")), COMMAND_TIMEOUT_MS);
      this.socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolveOpen();
      }, { once: true });
      this.socket.addEventListener("error", () => {
        clearTimeout(timer);
        rejectOpen(new SmokeError("CDP WebSocket failed"));
      }, { once: true });
    });
    this.socket.addEventListener("message", (event) => this.#message(event));
    this.socket.addEventListener("close", () => this.#close());
  }

  #message(event) {
    let message;
    try {
      message = JSON.parse(String(event.data));
    } catch {
      return;
    }
    if (!Number.isSafeInteger(message.id)) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.error) pending.reject(new SmokeError(`CDP command rejected: ${message.error.message || "unknown"}`));
    else pending.resolve(message.result || {});
  }

  #close() {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(new SmokeError("CDP connection closed"));
    }
    this.pending.clear();
  }

  command(method, params = {}, sessionId = undefined) {
    assertCdpMethodAllowed(method);
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new SmokeError("CDP WebSocket is not open");
    }
    const id = this.nextId++;
    this.methodCounts.set(method, (this.methodCounts.get(method) || 0) + 1);
    return new Promise((resolveCommand, rejectCommand) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        rejectCommand(new SmokeError(`CDP command timed out: ${method}`));
      }, COMMAND_TIMEOUT_MS);
      this.pending.set(id, { resolve: resolveCommand, reject: rejectCommand, timer });
      this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }

  close() {
    this.socket?.close();
  }

  commandSummary() {
    return [...this.methodCounts.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([method, count]) => Object.freeze({ count, method }));
  }
}

function check(assertions, name, condition) {
  assertions.push(Object.freeze({ name, passed: condition === true }));
  if (condition !== true) throw new SmokeError(`extension smoke assertion failed: ${name}`);
}

function exactKeys(value, expected, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new SmokeError(`${label} is not an object`);
  }
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new SmokeError(`${label} fields are not exact`);
  }
  return value;
}

export function validateSmokeReport(report) {
  exactKeys(
    report,
    [
      "actionExecuted",
      "assertions",
      "cdpProbe",
      "extension",
      "externalNavigationExecuted",
      "limitations",
      "redaction",
      "runtime",
      "schemaVersion",
      "scope",
      "status",
    ],
    "smoke report",
  );
  if (
    report.schemaVersion !== 2 ||
    report.status !== "PASS" ||
    report.scope !== "OPENCV_CNSE_SITE_EXTENSION_LOAD_ONLY" ||
    report.actionExecuted !== false ||
    report.externalNavigationExecuted !== false
  ) {
    throw new SmokeError("smoke report status or scope is invalid");
  }
  if (
    !Array.isArray(report.assertions) ||
    report.assertions.length !== SMOKE_ASSERTION_NAMES.length
  ) {
    throw new SmokeError("smoke report assertions are invalid");
  }
  const assertionNames = new Set();
  for (const [index, assertion] of report.assertions.entries()) {
    exactKeys(assertion, ["name", "passed"], "smoke assertion");
    if (
      typeof assertion.name !== "string" ||
      !/^[a-z][a-z0-9_]{2,63}$/u.test(assertion.name) ||
      assertion.name !== SMOKE_ASSERTION_NAMES[index] ||
      assertion.passed !== true ||
      assertionNames.has(assertion.name)
    ) {
      throw new SmokeError("smoke report assertion is invalid, failed, or duplicated");
    }
    assertionNames.add(assertion.name);
  }
  exactKeys(
    report.extension,
    [
      "algorithm",
      "buildStatus",
      "externalTargetsAllowed",
      "id",
      "installType",
      "opencvVersion",
      "solveEnabled",
      "version",
    ],
    "smoke extension",
  );
  if (
    !EXTENSION_ID_RE.test(report.extension.id) ||
    !/^\d{1,6}\.\d{1,6}\.\d{1,6}(?:\.\d{1,6})?$/u.test(report.extension.version) ||
    report.extension.installType !== "development" ||
    report.extension.buildStatus !== "OPENCV_CNSE_SITE" ||
    report.extension.solveEnabled !== true ||
    report.extension.algorithm !== "opencv-edge-template-v1" ||
    report.extension.opencvVersion !== "4.13.0" ||
    report.extension.externalTargetsAllowed !== false
  ) {
    throw new SmokeError("smoke extension binding is invalid");
  }
  exactKeys(
    report.runtime,
    ["architecture", "browserProduct", "platform", "protocolVersion", "supportContract"],
    "smoke runtime",
  );
  if (
    !/^(?:Chrome|HeadlessChrome)\/\d{1,6}(?:\.\d{1,6}){3}$/u.test(report.runtime.browserProduct) ||
    !/^\d{1,6}\.\d{1,6}$/u.test(report.runtime.protocolVersion) ||
    hostContract(report.runtime.platform, report.runtime.architecture) !== report.runtime.supportContract
  ) {
    throw new SmokeError("smoke runtime support contract is invalid");
  }
  exactKeys(
    report.cdpProbe,
    [
      "commandSummary",
      "extensionDebuggerApiAvailable",
      "extensionDebuggerAttached",
      "inputCommandCount",
      "networkCommandCount",
      "pageNavigationCommandCount",
      "transport",
    ],
    "smoke CDP probe",
  );
  if (
    report.cdpProbe.transport !== "loopback-browser-devtools" ||
    report.cdpProbe.extensionDebuggerApiAvailable !== true ||
    report.cdpProbe.extensionDebuggerAttached !== false ||
    report.cdpProbe.inputCommandCount !== 0 ||
    report.cdpProbe.networkCommandCount !== 0 ||
    report.cdpProbe.pageNavigationCommandCount !== 0 ||
    !Array.isArray(report.cdpProbe.commandSummary) ||
    report.cdpProbe.commandSummary.length === 0 ||
    report.cdpProbe.commandSummary.length > ALLOWED_CDP_METHODS.size
  ) {
    throw new SmokeError("smoke CDP probe is not load-only");
  }
  let previousMethod = "";
  for (const entry of report.cdpProbe.commandSummary) {
    exactKeys(entry, ["count", "method"], "smoke CDP command summary");
    assertCdpMethodAllowed(entry.method);
    if (
      entry.method <= previousMethod ||
      !Number.isSafeInteger(entry.count) ||
      entry.count < 1 ||
      entry.count > 100
    ) {
      throw new SmokeError("smoke CDP command summary is invalid or duplicated");
    }
    previousMethod = entry.method;
  }
  exactKeys(
    report.redaction,
    ["credentialsRetained", "imageBytesRetained", "urlsRetained"],
    "smoke redaction",
  );
  if (Object.values(report.redaction).some((value) => value !== false)) {
    throw new SmokeError("smoke report retained sensitive evidence");
  }
  if (
    !Array.isArray(report.limitations) ||
    report.limitations.length !== 4 ||
    report.limitations.some((item) => typeof item !== "string" || item.length < 20 || item.length > 256)
  ) {
    throw new SmokeError("smoke report limitations are invalid");
  }
  const serialized = JSON.stringify(report);
  if (new TextEncoder().encode(serialized).byteLength > 64 * 1024 || /(?:https?|chrome-extension):\/\//u.test(serialized)) {
    throw new SmokeError("smoke report is oversized or retained a URL");
  }
  return report;
}

async function evaluateTarget(client, targetId, expression, label) {
  const attached = await client.command("Target.attachToTarget", { targetId, flatten: true });
  if (typeof attached.sessionId !== "string") throw new SmokeError(`${label} could not be attached`);
  let response;
  try {
    response = await client.command(
      "Runtime.evaluate",
      { expression, awaitPromise: true, returnByValue: true },
      attached.sessionId,
    );
  } finally {
    await client.command("Target.detachFromTarget", { sessionId: attached.sessionId });
  }
  if (response.exceptionDetails || !response.result || typeof response.result.value !== "object") {
    const detail = String(
      response.exceptionDetails?.exception?.description ||
      response.exceptionDetails?.text ||
      response.result?.description ||
      "",
    ).replace(/[\u0000-\u001f\u007f]+/gu, " ").slice(0, 240);
    throw new SmokeError(`${label} evaluation failed${detail ? `: ${detail}` : ""}`);
  }
  return response.result.value;
}

async function retryEvaluation(operation, label) {
  const deadline = Date.now() + COMMAND_TIMEOUT_MS;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      await delay(150);
    }
  }
  throw new SmokeError(`${label} did not become ready: ${lastError?.message || "evaluation failed"}`);
}

async function evaluateExtensionPage(client, targetId, expectedId) {
  const expression = `
    ({
      documentReady:document.readyState==="complete",
      extensionLocationExact:
        globalThis.location?.protocol==="chrome-extension:"&&
        globalThis.location?.host===${JSON.stringify(expectedId)}&&
        globalThis.location?.pathname==="/popup/popup.html",
      popupTriggerPresent:
        document.querySelectorAll("#run-drag-test").length===1&&
        document.querySelector("#run-drag-test")?.tagName==="BUTTON"
    })
  `;
  return evaluateTarget(client, targetId, expression, "extension page");
}

async function evaluateServiceWorker(client, targetId) {
  const expression = `
    (async()=>{
      const manifest=chrome.runtime.getManifest();
      const configResponse=await fetch(chrome.runtime.getURL("build-config.json"),{cache:"no-store"});
      const config=await configResponse.json();
      const configKeys=Object.keys(config).sort();
      const expectedConfigKeys=[
        "algorithm",
        "extensionId",
        "externalTargetsAllowed",
        "minimumChromeVersion",
        "opencvVersion",
        "remoteCodeAllowed",
        "schemaVersion",
        "solveEnabled",
        "status"
      ].sort();
      const resourcePresent=async(path)=>{
        try {
          const response=await fetch(chrome.runtime.getURL(path),{cache:"no-store"});
          const present=response.ok;
          try { await response.body?.cancel(); } catch {}
          return present;
        } catch {
          return false;
        }
      };
      const lockResponse=await fetch(chrome.runtime.getURL("vendor/opencv/lock.json"),{cache:"no-store"});
      let opencvLock=null;
      try { opencvLock=lockResponse.ok?await lockResponse.json():null; } catch { opencvLock=null; }
      const [opencvArtifactPresent,opencvLicensePresent]=await Promise.all([
        resourcePresent("vendor/opencv/opencv.js"),
        resourcePresent("vendor/opencv/LICENSE")
      ]);
      const manifestPermissions=Array.isArray(manifest.permissions)?[...manifest.permissions].sort():[];
      const manifestHostPermissions=Array.isArray(manifest.host_permissions)
        ?[...manifest.host_permissions].sort():[];
      return {
        runtimeId:chrome.runtime.id,
        extensionOrigin:globalThis.location?.protocol==="chrome-extension:",
        manifestVersion:manifest.manifest_version,
        extensionVersion:manifest.version,
        minimumChromeVersion:manifest.minimum_chrome_version,
        manifestBackgroundExact:
          manifest.background?.service_worker==="src/service-worker.js"&&
          manifest.background?.type==="module",
        manifestPermissionsExact:
          manifestPermissions.join(",")==="offscreen,scripting,tabs",
        manifestCnseSiteExact:
          manifestHostPermissions.length===1&&
          manifestHostPermissions[0]==="https://cnse.e-cqs.cn/*",
        manifestCspExact:
          manifest.content_security_policy?.extension_pages===
            "script-src 'self' 'wasm-unsafe-eval'; object-src 'self';",
        configContractExact:
          configResponse.ok&&configKeys.join(",")===expectedConfigKeys.join(",")&&
          config.schemaVersion===2&&config.minimumChromeVersion===120,
        buildStatus:config.status,
        solveEnabled:config.solveEnabled,
        algorithm:config.algorithm,
        opencvVersion:config.opencvVersion,
        externalTargetsAllowed:config.externalTargetsAllowed,
        remoteCodeAllowed:config.remoteCodeAllowed,
        extensionId:config.extensionId,
        opencvArtifactPresent,
        opencvLockPresent:lockResponse.ok&&opencvLock!==null,
        opencvLicensePresent,
        opencvLockExact:
          opencvLock?.schemaVersion===1&&
          opencvLock?.name==="OpenCV.js"&&
          opencvLock?.version==="4.13.0"&&
          opencvLock?.artifactFile==="opencv.js"&&
          opencvLock?.embeddedWasm===true&&
          opencvLock?.remoteCodeRequiredAtRuntime===false&&
          opencvLock?.dynamicJavascriptExecution===false,
        debuggerPermissionAbsent:!manifestPermissions.includes("debugger"),
        storageApiAbsent:typeof chrome.storage==="undefined"
      };
    })()
  `;
  return evaluateTarget(client, targetId, expression, "extension service worker");
}

export function chromeLaunchArguments(extensionRoot, profile) {
  return Object.freeze([
    "--headless=new",
    "--no-first-run",
    "--disable-default-apps",
    "--disable-background-networking",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-component-update",
    "--disable-crash-reporter",
    "--disable-domain-reliability",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-pings",
    "--no-proxy-server",
    "--password-store=basic",
    "--safebrowsing-disable-auto-update",
    "--use-mock-keychain",
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--disable-features=AutofillServerCommunication,DialMediaRouteProvider,MediaRouter,OptimizationHints",
    `--disable-extensions-except=${extensionRoot}`,
    `--load-extension=${extensionRoot}`,
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "about:blank",
  ]);
}

export async function runSmoke(options) {
  await requireFile(options.chrome, "Chrome executable");
  await requireDirectory(options.extensionRoot, "extension root");
  await requireFile(join(options.extensionRoot, "manifest.json"), "extension manifest");
  const temporaryRoot = await mkdtemp(join(tmpdir(), "captcha-safe-extension-smoke-"));
  const profile = join(temporaryRoot, "profile");
  const environment = sanitizedChromeEnvironment(process.env, temporaryRoot, process.platform);
  await Promise.all([
    mkdir(environment.HOME, { recursive: true, mode: 0o700 }),
    mkdir(environment.TMPDIR, { recursive: true, mode: 0o700 }),
    ...(process.platform === "win32"
      ? [
          mkdir(environment.APPDATA, { recursive: true, mode: 0o700 }),
          mkdir(environment.LOCALAPPDATA, { recursive: true, mode: 0o700 }),
        ]
      : []),
  ]);
  const extensionPage = `chrome-extension://${options.expectedId}/popup/popup.html`;
  const child = spawn(
    options.chrome,
    chromeLaunchArguments(options.extensionRoot, profile),
    { env: environment, stdio: ["ignore", "pipe", "pipe"] },
  );
  child.spawnFailure = null;
  child.once("error", (error) => {
    child.spawnFailure = error;
  });
  const stdout = boundedDiagnostic(child.stdout);
  const stderr = boundedDiagnostic(child.stderr);
  let client = null;
  try {
    const port = await readDevToolsPort(profile, child);
    const version = await boundedJson(`http://127.0.0.1:${port}/json/version`);
    if (typeof version.webSocketDebuggerUrl !== "string") {
      throw new SmokeError("DevTools browser WebSocket URL is missing");
    }
    client = new CdpClient(validateBrowserWebSocketUrl(version.webSocketDebuggerUrl, port));
    await client.connect();
    const browserVersion = await client.command("Browser.getVersion");
    const created = await client.command("Target.createTarget", { url: extensionPage });
    if (typeof created.targetId !== "string") throw new SmokeError("extension page target was not created");
    let targets = [];
    const deadline = Date.now() + COMMAND_TIMEOUT_MS;
    while (Date.now() < deadline) {
      targets = (await client.command("Target.getTargets")).targetInfos || [];
      if (!Array.isArray(targets) || targets.length > 64) {
        throw new SmokeError("Chrome returned an invalid or oversized target inventory");
      }
      if (targets.some((target) => target.type === "service_worker" && target.url === `chrome-extension://${options.expectedId}/src/service-worker.js`)) break;
      await delay(50);
    }
    const page = targets.find((target) => target.targetId === created.targetId && target.url === extensionPage);
    const worker = targets.find((target) => target.type === "service_worker" && target.url === `chrome-extension://${options.expectedId}/src/service-worker.js`);
    const pageRuntime = await retryEvaluation(
      () => evaluateExtensionPage(client, created.targetId, options.expectedId),
      "extension page",
    );
    if (!worker) {
      throw new SmokeError(
        "extension service worker target is missing; unpacked extension registration was not observed " +
          "(branded Chrome may ignore --load-extension; use Chrome for Testing or Chromium)",
      );
    }
    const workerRuntime = await retryEvaluation(
      () => evaluateServiceWorker(client, worker.targetId),
      "extension service worker",
    );
    const commandSummary = client.commandSummary();
    const inputCommandCount = commandSummary
      .filter(({ method }) => method.startsWith("Input."))
      .reduce((total, { count }) => total + count, 0);
    const networkCommandCount = commandSummary
      .filter(({ method }) => method.startsWith("Network.") || method.startsWith("Fetch."))
      .reduce((total, { count }) => total + count, 0);
    const pageNavigationCommandCount = commandSummary
      .filter(({ method }) => method === "Page.navigate")
      .reduce((total, { count }) => total + count, 0);
    const assertions = [];
    check(assertions, "host_platform_exact", process.platform === options.expectedPlatform);
    check(assertions, "host_architecture_exact", process.arch === options.expectedArchitecture);
    check(
      assertions,
      "host_support_contract_exact",
      hostContract(process.platform, process.arch) === options.expectedHostContract,
    );
    check(
      assertions,
      "extension_page_loaded",
      Boolean(page) &&
        pageRuntime.documentReady === true &&
        pageRuntime.extensionLocationExact === true &&
        pageRuntime.popupTriggerPresent === true,
    );
    check(assertions, "service_worker_loaded", Boolean(worker));
    check(assertions, "runtime_extension_id_exact", workerRuntime.runtimeId === options.expectedId);
    check(assertions, "config_extension_id_exact", workerRuntime.extensionId === options.expectedId);
    check(assertions, "manifest_v3", workerRuntime.manifestVersion === 3);
    check(assertions, "minimum_chrome_120", workerRuntime.minimumChromeVersion === "120");
    check(assertions, "manifest_background_exact", workerRuntime.manifestBackgroundExact === true);
    check(assertions, "manifest_permissions_exact", workerRuntime.manifestPermissionsExact === true);
    check(assertions, "manifest_cnse_site_exact", workerRuntime.manifestCnseSiteExact === true);
    check(assertions, "manifest_csp_exact", workerRuntime.manifestCspExact === true);
    check(assertions, "config_contract_exact", workerRuntime.configContractExact === true);
    check(assertions, "opencv_cnse_site_status", workerRuntime.buildStatus === "OPENCV_CNSE_SITE");
    check(assertions, "solve_enabled", workerRuntime.solveEnabled === true);
    check(assertions, "solver_algorithm_exact", workerRuntime.algorithm === "opencv-edge-template-v1");
    check(assertions, "opencv_version_exact", workerRuntime.opencvVersion === "4.13.0");
    check(assertions, "external_targets_disabled", workerRuntime.externalTargetsAllowed === false);
    check(assertions, "remote_code_disabled", workerRuntime.remoteCodeAllowed === false);
    check(assertions, "opencv_vendor_artifact_present", workerRuntime.opencvArtifactPresent === true);
    check(assertions, "opencv_vendor_lock_present", workerRuntime.opencvLockPresent === true);
    check(assertions, "opencv_vendor_license_present", workerRuntime.opencvLicensePresent === true);
    check(assertions, "opencv_vendor_lock_exact", workerRuntime.opencvLockExact === true);
    check(assertions, "extension_debugger_permission_absent", workerRuntime.debuggerPermissionAbsent === true);
    check(assertions, "extension_storage_api_absent", workerRuntime.storageApiAbsent === true);
    check(assertions, "worker_runtime_id_exact", workerRuntime.runtimeId === options.expectedId);
    check(assertions, "worker_extension_origin", workerRuntime.extensionOrigin === true);
    check(assertions, "worker_debugger_permission_absent", workerRuntime.debuggerPermissionAbsent === true);
    check(assertions, "worker_storage_api_absent", workerRuntime.storageApiAbsent === true);
    check(assertions, "cdp_input_commands_zero", inputCommandCount === 0);
    check(assertions, "cdp_network_commands_zero", networkCommandCount === 0);
    check(assertions, "cdp_page_navigation_commands_zero", pageNavigationCommandCount === 0);
    check(
      assertions,
      "browser_version_exact",
      browserVersion.product === `Chrome/${options.expectedVersion}` ||
        browserVersion.product === `HeadlessChrome/${options.expectedVersion}`,
    );
    return validateSmokeReport({
      schemaVersion: 2,
      status: "PASS",
      scope: "OPENCV_CNSE_SITE_EXTENSION_LOAD_ONLY",
      actionExecuted: false,
      externalNavigationExecuted: false,
      assertions,
      extension: {
        id: options.expectedId,
        version: workerRuntime.extensionVersion,
        installType: "development",
        buildStatus: workerRuntime.buildStatus,
        solveEnabled: workerRuntime.solveEnabled,
        algorithm: workerRuntime.algorithm,
        opencvVersion: workerRuntime.opencvVersion,
        externalTargetsAllowed: workerRuntime.externalTargetsAllowed,
      },
      runtime: {
        browserProduct: browserVersion.product,
        protocolVersion: browserVersion.protocolVersion,
        platform: process.platform,
        architecture: process.arch,
        supportContract: options.expectedHostContract,
      },
      cdpProbe: {
        transport: "loopback-browser-devtools",
        commandSummary,
        inputCommandCount,
        networkCommandCount,
        pageNavigationCommandCount,
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
        "The probe opened only about:blank and the extension-owned popup; no external origin was navigated.",
        "Chrome background networking was disabled, but this probe is not an OS-level egress audit.",
        "This smoke test validates local loading and static contracts, not recognition or drag geometry.",
      ],
    });
  } catch (error) {
    const diagnostic = [stderr(), stdout()].filter(Boolean).join(" | ");
    throw new SmokeError(`${error?.message || "extension smoke failed"}${diagnostic ? ` (${diagnostic})` : ""}`);
  } finally {
    if (client) {
      try {
        await client.command("Browser.close");
      } catch {
        // Closing or crashed Chrome is already a terminal smoke-test state.
      }
      client.close();
    }
    if (child.exitCode === null) child.kill("SIGTERM");
    await Promise.race([
      new Promise((resolveExit) => child.once("exit", resolveExit)),
      delay(2000),
    ]);
    if (child.exitCode === null) child.kill("SIGKILL");
    if (child.exitCode === null) {
      await Promise.race([
        new Promise((resolveExit) => child.once("exit", resolveExit)),
        delay(2000),
      ]);
    }
    await rm(temporaryRoot, { recursive: true, force: true });
  }
}

export async function main(argv = process.argv.slice(2)) {
  const options = parseArguments(argv);
  const report = await runSmoke(options);
  const body = `${JSON.stringify(report, null, 2)}\n`;
  await writeFile(options.output, body, { encoding: "utf8", flag: "wx" });
  process.stdout.write(body);
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) {
  main().catch((error) => {
    process.stderr.write(`Chrome extension smoke failed: ${error?.message || "unknown error"}\n`);
    process.exitCode = 1;
  });
}
