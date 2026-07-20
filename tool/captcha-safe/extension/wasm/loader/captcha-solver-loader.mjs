const ABI_VERSION = 1;
const CONFIG_SIZE = 56;
const RESULT_SIZE = 112;
const FIXED_MEMORY_BYTES = 16_777_216;
const TARGET_RGB_CAPACITY = 196_608;
const BACKGROUND_RGB_CAPACITY = 1_572_864;
const ALGORITHM_ID = "captcha-safe-canny-like-ncc-v1";
const SOLVER_READINESS = "PENDING";
const SHA256_PATTERN = /^[a-f0-9]{64}$/;

const REQUIRED_FUNCTIONS = Object.freeze([
  "solver_abi_version",
  "solver_config_size",
  "solver_result_size",
  "solver_target_rgb_capacity",
  "solver_background_rgb_capacity",
  "solver_target_rgb",
  "solver_background_rgb",
  "solver_config",
  "solver_result",
  "solver_reset",
  "solver_solve",
]);

export class CaptchaSolverLoadError extends Error {
  constructor(code, message, result = null) {
    super(message);
    this.name = "CaptchaSolverLoadError";
    this.code = code;
    this.result = result;
  }
}

function fail(code, message, result = null) {
  throw new CaptchaSolverLoadError(code, message, result);
}

function exportedFunction(exports, name) {
  const value = exports[name] ?? exports[`_${name}`];
  if (typeof value !== "function") fail("ABI_INVALID", `missing WASM export: ${name}`);
  return value;
}

function uint32(value, label) {
  if (!Number.isSafeInteger(value)) fail("ABI_INVALID", `${label} is not an integer`);
  return value >>> 0;
}

function exactPositiveInteger(value, label) {
  if (!Number.isSafeInteger(value) || value <= 0 || value > 0xffff_ffff) {
    fail("INPUT_INVALID", `${label} is not a positive uint32`);
  }
  return value;
}

function requireRgb(value, expectedLength, label) {
  if (!(value instanceof Uint8Array) || value.byteLength !== expectedLength) {
    fail("INPUT_INVALID", `${label} must be an exact-length Uint8Array`);
  }
}

async function sha256Hex(bytes, cryptoProvider) {
  if (!cryptoProvider?.subtle?.digest) {
    fail("CRYPTO_UNAVAILABLE", "WebCrypto SHA-256 is unavailable");
  }
  let digest;
  try {
    digest = new Uint8Array(await cryptoProvider.subtle.digest("SHA-256", bytes));
  } catch {
    fail("CRYPTO_UNAVAILABLE", "WebCrypto SHA-256 failed");
  }
  return [...digest].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function parseResult(memory, pointer) {
  let view;
  try {
    view = new DataView(memory.buffer, pointer, RESULT_SIZE);
  } catch {
    fail("ABI_INVALID", "solver result pointer is outside fixed memory");
  }
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
    reserved0: view.getUint32(104, true),
    reserved1: view.getUint32(108, true),
  });
}

function validateRanges(memoryBytes, ranges) {
  const ordered = [...ranges].sort((left, right) => left.start - right.start);
  for (const range of ordered) {
    if (
      !Number.isSafeInteger(range.start) ||
      !Number.isSafeInteger(range.size) ||
      range.start < 0 ||
      range.size <= 0 ||
      range.start + range.size > memoryBytes
    ) {
      fail("ABI_INVALID", `${range.label} is outside fixed memory`);
    }
  }
  for (let index = 1; index < ordered.length; index += 1) {
    if (ordered[index - 1].start + ordered[index - 1].size > ordered[index].start) {
      fail("ABI_INVALID", "solver ABI buffers overlap");
    }
  }
}

class CaptchaSolverInstance {
  #memory;
  #functions;
  #pointers;

  constructor(memory, functions, pointers, digest) {
    this.#memory = memory;
    this.#functions = functions;
    this.#pointers = pointers;
    this.wasmSha256 = digest;
    this.abiVersion = ABI_VERSION;
    this.algorithmId = ALGORITHM_ID;
    this.solverReadiness = "PENDING";
    this.opencvParity = false;
    this.actionAuthorized = false;
    Object.freeze(this);
  }

  solve({ targetWidth, targetHeight, backgroundWidth, backgroundHeight, targetRgb, backgroundRgb }) {
    const targetWidthValue = exactPositiveInteger(targetWidth, "targetWidth");
    const targetHeightValue = exactPositiveInteger(targetHeight, "targetHeight");
    const backgroundWidthValue = exactPositiveInteger(backgroundWidth, "backgroundWidth");
    const backgroundHeightValue = exactPositiveInteger(backgroundHeight, "backgroundHeight");
    const targetBytes = targetWidthValue * targetHeightValue * 3;
    const backgroundBytes = backgroundWidthValue * backgroundHeightValue * 3;
    if (
      !Number.isSafeInteger(targetBytes) ||
      !Number.isSafeInteger(backgroundBytes) ||
      targetBytes > TARGET_RGB_CAPACITY ||
      backgroundBytes > BACKGROUND_RGB_CAPACITY
    ) {
      fail("INPUT_INVALID", "RGB input exceeds the fixed solver capacity");
    }
    requireRgb(targetRgb, targetBytes, "targetRgb");
    requireRgb(backgroundRgb, backgroundBytes, "backgroundRgb");

    this.#functions.reset();
    new Uint8Array(this.#memory.buffer, this.#pointers.target, targetBytes).set(targetRgb);
    new Uint8Array(this.#memory.buffer, this.#pointers.background, backgroundBytes).set(
      backgroundRgb,
    );
    const returnCode = this.#functions.solve(
      targetWidthValue,
      targetHeightValue,
      backgroundWidthValue,
      backgroundHeightValue,
      targetBytes,
      backgroundBytes,
    );
    const result = parseResult(this.#memory, this.#pointers.result);
    if (
      result.abiVersion !== ABI_VERSION ||
      result.structSize !== RESULT_SIZE ||
      result.reserved0 !== 0 ||
      result.reserved1 !== 0
    ) {
      fail("ABI_INVALID", "solver returned an invalid result structure");
    }
    if (returnCode !== 0) {
      fail("SOLVER_ERROR", `solver returned controlled error ${returnCode}`, result);
    }
    if (![1, 2].includes(result.decision)) {
      fail("ABI_INVALID", "completed solver result has an invalid decision");
    }
    if ((result.decision === 1 && result.reason !== 0) || (result.decision === 2 && result.reason === 0)) {
      fail("ABI_INVALID", "solver decision and reason are inconsistent");
    }
    if (
      result.targetWidth !== targetWidthValue ||
      result.targetHeight !== targetHeightValue ||
      result.backgroundWidth !== backgroundWidthValue ||
      result.backgroundHeight !== backgroundHeightValue
    ) {
      fail("ABI_INVALID", "solver result dimensions do not match the request");
    }
    return Object.freeze({
      solverReadiness: SOLVER_READINESS,
      algorithmId: ALGORITHM_ID,
      opencvParity: false,
      actionAuthorized: false,
      result,
    });
  }
}

export async function instantiateCaptchaSolver({
  wasmBytes,
  expectedSha256,
  cryptoProvider = globalThis.crypto,
}) {
  if (!(wasmBytes instanceof Uint8Array) || wasmBytes.byteLength === 0) {
    fail("INPUT_INVALID", "wasmBytes must be a non-empty Uint8Array");
  }
  if (typeof expectedSha256 !== "string" || !SHA256_PATTERN.test(expectedSha256)) {
    fail("INPUT_INVALID", "expectedSha256 must be a lowercase SHA-256 digest");
  }
  const immutableBytes = wasmBytes.slice();
  const actualSha256 = await sha256Hex(immutableBytes, cryptoProvider);
  if (actualSha256 !== expectedSha256) {
    fail("DIGEST_MISMATCH", "WASM digest does not match the trusted package manifest");
  }
  if (!WebAssembly.validate(immutableBytes)) fail("WASM_INVALID", "WASM binary is invalid");

  let module;
  try {
    module = await WebAssembly.compile(immutableBytes);
  } catch {
    fail("WASM_INVALID", "WASM compilation failed");
  }
  if (WebAssembly.Module.imports(module).length !== 0) {
    fail("ABI_INVALID", "solver WASM must not import host capabilities");
  }
  let instance;
  try {
    instance = await WebAssembly.instantiate(module, Object.create(null));
  } catch {
    fail("WASM_INVALID", "WASM instantiation failed");
  }
  const exports = instance.exports;
  if (!(exports.memory instanceof WebAssembly.Memory)) {
    fail("ABI_INVALID", "solver WASM does not export linear memory");
  }
  if (exports.memory.buffer.byteLength !== FIXED_MEMORY_BYTES) {
    fail("ABI_INVALID", "solver WASM memory is not exactly 16 MiB");
  }
  try {
    exports.memory.grow(1);
    fail("ABI_INVALID", "solver WASM unexpectedly permits memory growth");
  } catch (error) {
    if (error instanceof CaptchaSolverLoadError) throw error;
    if (!(error instanceof RangeError)) fail("ABI_INVALID", "solver memory growth check failed");
  }

  const functions = Object.fromEntries(
    REQUIRED_FUNCTIONS.map((name) => [name, exportedFunction(exports, name)]),
  );
  if (
    functions.solver_abi_version() !== ABI_VERSION ||
    functions.solver_config_size() !== CONFIG_SIZE ||
    functions.solver_result_size() !== RESULT_SIZE ||
    functions.solver_target_rgb_capacity() !== TARGET_RGB_CAPACITY ||
    functions.solver_background_rgb_capacity() !== BACKGROUND_RGB_CAPACITY
  ) {
    fail("ABI_INVALID", "solver ABI version, sizes, or capacities do not match v1");
  }
  const pointers = Object.freeze({
    target: uint32(functions.solver_target_rgb(), "target RGB pointer"),
    background: uint32(functions.solver_background_rgb(), "background RGB pointer"),
    config: uint32(functions.solver_config(), "config pointer"),
    result: uint32(functions.solver_result(), "result pointer"),
  });
  validateRanges(FIXED_MEMORY_BYTES, [
    { label: "target RGB buffer", start: pointers.target, size: TARGET_RGB_CAPACITY },
    { label: "background RGB buffer", start: pointers.background, size: BACKGROUND_RGB_CAPACITY },
    { label: "config", start: pointers.config, size: CONFIG_SIZE },
    { label: "result", start: pointers.result, size: RESULT_SIZE },
  ]);
  functions.solver_reset();
  return new CaptchaSolverInstance(
    exports.memory,
    Object.freeze({ reset: functions.solver_reset, solve: functions.solver_solve }),
    pointers,
    actualSha256,
  );
}

export const CAPTCHA_SOLVER_CONTRACT = Object.freeze({
  abiVersion: ABI_VERSION,
  algorithmId: ALGORITHM_ID,
  solverReadiness: "PENDING",
  fixedMemoryBytes: FIXED_MEMORY_BYTES,
  opencvParity: false,
  actionAuthorized: false,
});
