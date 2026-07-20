const VERSION = 1;
const MAX_MESSAGE_BYTES = 32768;
const REQUEST_ID = /^[A-Za-z0-9_-]{24}$/u;

export class ProtocolError extends Error {
  constructor(message) {
    super(message);
    this.name = "ProtocolError";
    this.code = "MESSAGE_INVALID";
  }
}

function invalid(message) {
  throw new ProtocolError(message);
}

export function exactObject(value, fields, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    invalid(`${label} must be an object`);
  }
  const actual = Object.keys(value).sort();
  const expected = [...fields].sort();
  if (actual.length !== expected.length || actual.some((field, index) => field !== expected[index])) {
    invalid(`${label} fields are not exact`);
  }
  return value;
}

export function requireString(value, label, { pattern, min = 1, max = 2048 } = {}) {
  if (typeof value !== "string") invalid(`${label} must be a string`);
  const length = new TextEncoder().encode(value).byteLength;
  if (length < min || length > max || (pattern && !pattern.test(value))) {
    invalid(`${label} is invalid`);
  }
  return value;
}

function requireInteger(value, label, minimum, maximum) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    invalid(`${label} is invalid`);
  }
  return value;
}

function requireNumber(value, label, minimum, maximum) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    invalid(`${label} is invalid`);
  }
  return value;
}

const PAYLOADS = Object.freeze({
  "solve.start": (payload) => {
    exactObject(payload, ["keyword"], "solve.start payload");
    requireString(payload.keyword, "solve.start keyword", { max: 512 });
  },
  "solve.result": (payload) => {
    exactObject(
      payload,
      [
        "algorithm",
        "apiYHeight",
        "captureMode",
        "confidence",
        "matchBox",
        "moveLength",
        "keyword",
        "queryEndpoint",
        "rows",
        "status",
        "targetCenter",
        "total",
      ],
      "solve.result payload",
    );
    if (
      payload.status !== "COMPLETED" ||
      payload.algorithm !== "opencv-edge-template-v1" ||
      payload.captureMode !== "api"
    ) {
      invalid("solve.result has an invalid completed state");
    }
    requireNumber(payload.confidence, "solve.result confidence", 0.5, 1);
    requireInteger(payload.apiYHeight, "solve.result apiYHeight", 0, 4096);
    requireNumber(payload.moveLength, "solve.result moveLength", 0, 65_535);
    requireString(payload.keyword, "solve.result keyword", { max: 512 });
    if (payload.queryEndpoint !== "/info-pub/pub/orgSearchData.json") {
      invalid("solve.result queryEndpoint is invalid");
    }
    requireInteger(payload.total, "solve.result total", 0, 1_000_000);
    if (!Array.isArray(payload.rows) || payload.rows.length > 10) {
      invalid("solve.result rows are invalid");
    }
    const rowFields = ["dwid", "fzjg", "zsyxq", "dwmc", "dwlb", "sjgxsj", "zsyxqyz"];
    for (const [index, row] of payload.rows.entries()) {
      exactObject(row, rowFields, `solve.result rows[${index}]`);
      for (const field of rowFields) {
        requireString(row[field], `solve.result rows[${index}].${field}`, { min: 0, max: 1024 });
      }
    }
    exactObject(payload.targetCenter, ["x", "y"], "solve.result targetCenter");
    requireInteger(payload.targetCenter.x, "solve.result targetCenter.x", 0, 65_535);
    requireInteger(payload.targetCenter.y, "solve.result targetCenter.y", 0, 65_535);
    exactObject(payload.matchBox, ["height", "width", "x", "y"], "solve.result matchBox");
    for (const field of ["height", "width", "x", "y"]) {
      requireInteger(payload.matchBox[field], `solve.result matchBox.${field}`, 0, 65_535);
    }
  },
  "response.error": (payload) => {
    exactObject(payload, ["code", "message"], "response.error payload");
    requireString(payload.code, "response.error code", {
      pattern: /^[A-Z_]{2,64}$/u,
      max: 64,
    });
    requireString(payload.message, "response.error message", { max: 256 });
  },
});

export function validateLocalMessage(value) {
  exactObject(value, ["payload", "request_id", "type", "v"], "local message");
  if (value.v !== VERSION) invalid("local message version is invalid");
  requireString(value.type, "local message type", {
    pattern: /^[a-z]+(?:\.[a-z]+)+$/u,
    max: 64,
  });
  requireString(value.request_id, "local message request_id", {
    pattern: REQUEST_ID,
    min: 24,
    max: 24,
  });
  const validator = PAYLOADS[value.type];
  if (!validator) invalid("local message type is not allowed");
  validator(value.payload);
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > MAX_MESSAGE_BYTES) {
    invalid("local message is oversized");
  }
  return value;
}

export function createLocalMessage({ type, requestId, payload }) {
  return validateLocalMessage({ v: VERSION, type, request_id: requestId, payload });
}

export function randomRequestId(cryptoProvider = globalThis.crypto) {
  if (!cryptoProvider || typeof cryptoProvider.getRandomValues !== "function") {
    invalid("secure request ID generation is unavailable");
  }
  const bytes = new Uint8Array(18);
  cryptoProvider.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const value = globalThis.btoa(binary)
    .replace(/\+/gu, "-")
    .replace(/\//gu, "_")
    .replace(/=+$/u, "");
  return requireString(value, "generated request_id", {
    pattern: REQUEST_ID,
    min: 24,
    max: 24,
  });
}

export function assertPopupSender(sender, extensionId) {
  if (
    !sender ||
    sender.id !== extensionId ||
    (sender.frameId !== undefined && sender.frameId !== 0)
  ) {
    invalid("local message sender is not the extension popup");
  }
  let url;
  try {
    url = new URL(sender.url);
  } catch {
    invalid("local message sender URL is invalid");
  }
  const origin = `chrome-extension://${extensionId}`;
  if (
    url.protocol !== "chrome-extension:" ||
    url.hostname !== extensionId ||
    url.pathname !== "/popup/popup.html" ||
    url.search ||
    url.hash ||
    (sender.origin !== undefined && sender.origin !== origin) ||
    (sender.tab?.url !== undefined && sender.tab.url !== url.href)
  ) {
    invalid("local message sender is outside the fixed popup");
  }
  return true;
}
