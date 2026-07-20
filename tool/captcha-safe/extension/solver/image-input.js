import {
  MAX_IMAGE_EDGE,
  MAX_IMAGE_PIXELS,
  OpenCvSolverError,
  validateRgbaImage,
} from "./opencv-solver.js";

export const MAX_ENCODED_IMAGE_BYTES = 8 * 1024 * 1024;
const MAX_DATA_URL_CHARACTERS = Math.ceil(MAX_ENCODED_IMAGE_BYTES * 4 / 3) + 256;
const FETCH_TIMEOUT_MS = 15_000;
const ALLOWED_RESOURCE_PROTOCOLS = new Set(["http:", "https:", "data:", "blob:"]);

function fail(code, message, options = undefined) {
  throw new OpenCvSolverError(code, message, options);
}

function exactObject(value, fields, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail("CAPTURE_INVALID", `${label} must be an object`);
  }
  const actual = Object.keys(value).sort();
  const expected = [...fields].sort();
  if (actual.length !== expected.length || actual.some((field, index) => field !== expected[index])) {
    fail("CAPTURE_INVALID", `${label} has unexpected fields`);
  }
  return value;
}

function finitePositive(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    fail("CAPTURE_INVALID", `${label} must be a positive finite number`);
  }
  return value;
}

function finiteNonNegative(value, label) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    fail("CAPTURE_INVALID", `${label} must be a non-negative finite number`);
  }
  return value;
}

function validateResourceUrl(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    fail("CAPTURE_INVALID", `${label} is missing`);
  }
  if (value.startsWith("data:") && value.length > MAX_DATA_URL_CHARACTERS) {
    fail("IMAGE_LIMIT_EXCEEDED", `${label} exceeds the encoded image limit`);
  }
  let url;
  try {
    url = new URL(value);
  } catch (error) {
    fail("CAPTURE_INVALID", `${label} is not a valid URL`, { cause: error });
  }
  if (!ALLOWED_RESOURCE_PROTOCOLS.has(url.protocol)) {
    fail("CAPTURE_INVALID", `${label} uses an unsupported URL scheme`);
  }
  return url.href;
}

function imageFormat(bytes) {
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
    bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a
  ) return "image/png";
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length >= 12 &&
    bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
    bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50
  ) return "image/webp";
  return null;
}

async function readBoundedResponse(response, label) {
  if (!response || !response.ok) {
    fail("IMAGE_FETCH_FAILED", `${label} could not be fetched`);
  }
  const declared = response.headers?.get?.("content-length");
  if (declared !== null && declared !== undefined && declared !== "") {
    const length = Number(declared);
    if (!Number.isSafeInteger(length) || length < 0) {
      fail("IMAGE_FETCH_FAILED", `${label} returned an invalid content length`);
    }
    if (length > MAX_ENCODED_IMAGE_BYTES) {
      fail("IMAGE_LIMIT_EXCEEDED", `${label} exceeds the encoded image limit`);
    }
  }

  if (!response.body?.getReader) {
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_ENCODED_IMAGE_BYTES) {
      fail("IMAGE_LIMIT_EXCEEDED", `${label} exceeds the encoded image limit`);
    }
    return new Uint8Array(buffer);
  }

  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (!value?.byteLength) continue;
      length += value.byteLength;
      if (length > MAX_ENCODED_IMAGE_BYTES) {
        await reader.cancel();
        fail("IMAGE_LIMIT_EXCEEDED", `${label} exceeds the encoded image limit`);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock?.();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function validateDecodedDimensions(width, height, label) {
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) {
    fail("IMAGE_DECODE_FAILED", `${label} has invalid dimensions`);
  }
  if (width > MAX_IMAGE_EDGE || height > MAX_IMAGE_EDGE || width * height > MAX_IMAGE_PIXELS) {
    fail("IMAGE_LIMIT_EXCEEDED", `${label} dimensions exceed the local processing limit`);
  }
}

export async function decodeImageUrl(
  url,
  label,
  {
    fetchProvider = globalThis.fetch,
    createImageBitmapProvider = globalThis.createImageBitmap,
    OffscreenCanvasProvider = globalThis.OffscreenCanvas,
  } = {},
) {
  const normalizedUrl = validateResourceUrl(url, label);
  if (typeof fetchProvider !== "function" || typeof createImageBitmapProvider !== "function") {
    fail("IMAGE_DECODE_FAILED", "browser image decoding is unavailable");
  }
  if (typeof OffscreenCanvasProvider !== "function") {
    fail("IMAGE_DECODE_FAILED", "offscreen canvas is unavailable");
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  let bytes;
  try {
    const response = await fetchProvider(normalizedUrl, {
      cache: "no-store",
      credentials: "include",
      signal: controller.signal,
    });
    bytes = await readBoundedResponse(response, label);
  } catch (error) {
    if (error instanceof OpenCvSolverError) throw error;
    fail("IMAGE_FETCH_FAILED", `${label} could not be fetched`, { cause: error });
  } finally {
    clearTimeout(timer);
  }

  const mimeType = imageFormat(bytes);
  if (!mimeType) {
    fail("IMAGE_FORMAT_UNSUPPORTED", `${label} is not a PNG, JPEG, or WebP image`);
  }

  let bitmap;
  try {
    bitmap = await createImageBitmapProvider(new Blob([bytes], { type: mimeType }));
    validateDecodedDimensions(bitmap.width, bitmap.height, label);
    const canvas = new OffscreenCanvasProvider(bitmap.width, bitmap.height);
    const context = canvas.getContext("2d", { alpha: true, willReadFrequently: true });
    if (!context) fail("IMAGE_DECODE_FAILED", `${label} could not create a 2D canvas`);
    context.drawImage(bitmap, 0, 0);
    const rgba = context.getImageData(0, 0, bitmap.width, bitmap.height).data;
    return validateRgbaImage({ width: bitmap.width, height: bitmap.height, data: rgba }, label);
  } catch (error) {
    if (error instanceof OpenCvSolverError) throw error;
    fail("IMAGE_DECODE_FAILED", `${label} could not be decoded`, { cause: error });
  } finally {
    bitmap?.close?.();
  }
}

function validateViewport(value) {
  exactObject(value, ["height", "width"], "viewport");
  return Object.freeze({
    width: finitePositive(value.width, "viewport.width"),
    height: finitePositive(value.height, "viewport.height"),
  });
}

function validateRect(value, label, viewport) {
  exactObject(value, ["height", "width", "x", "y"], label);
  const rect = Object.freeze({
    x: finiteNonNegative(value.x, `${label}.x`),
    y: finiteNonNegative(value.y, `${label}.y`),
    width: finitePositive(value.width, `${label}.width`),
    height: finitePositive(value.height, `${label}.height`),
  });
  const tolerance = 0.5;
  if (rect.x + rect.width > viewport.width + tolerance || rect.y + rect.height > viewport.height + tolerance) {
    fail("CAPTURE_INVALID", `${label} is not fully visible in the captured viewport`);
  }
  return rect;
}

function pixelRect(rect, viewport, image) {
  const scaleX = image.width / viewport.width;
  const scaleY = image.height / viewport.height;
  const relativeScaleError = Math.abs(scaleX - scaleY) / Math.max(scaleX, scaleY);
  if (!Number.isFinite(relativeScaleError) || relativeScaleError > 0.02) {
    fail("CAPTURE_SCALE_INVALID", "the screenshot is not uniformly scaled from the viewport");
  }
  const left = Math.max(0, Math.floor(rect.x * scaleX));
  const top = Math.max(0, Math.floor(rect.y * scaleY));
  const right = Math.min(image.width, Math.ceil((rect.x + rect.width) * scaleX));
  const bottom = Math.min(image.height, Math.ceil((rect.y + rect.height) * scaleY));
  if (right <= left || bottom <= top) fail("CAPTURE_INVALID", "a screenshot crop is empty");
  return Object.freeze({ x: left, y: top, width: right - left, height: bottom - top });
}

export function cropRgba(image, rect) {
  const source = validateRgbaImage(image, "screenshot");
  if (
    !rect ||
    !Number.isSafeInteger(rect.x) ||
    !Number.isSafeInteger(rect.y) ||
    !Number.isSafeInteger(rect.width) ||
    !Number.isSafeInteger(rect.height) ||
    rect.x < 0 || rect.y < 0 || rect.width <= 0 || rect.height <= 0 ||
    rect.x + rect.width > source.width || rect.y + rect.height > source.height
  ) {
    fail("CAPTURE_INVALID", "screenshot crop coordinates are invalid");
  }
  const data = new Uint8ClampedArray(rect.width * rect.height * 4);
  const rowBytes = rect.width * 4;
  for (let row = 0; row < rect.height; row += 1) {
    const sourceOffset = ((rect.y + row) * source.width + rect.x) * 4;
    data.set(source.data.subarray(sourceOffset, sourceOffset + rowBytes), row * rowBytes);
  }
  return Object.freeze({ width: rect.width, height: rect.height, data });
}

export function differenceRgba(normal, hidden) {
  const normalImage = validateRgbaImage(normal, "normal screenshot crop");
  const hiddenImage = validateRgbaImage(hidden, "hidden screenshot crop");
  if (normalImage.width !== hiddenImage.width || normalImage.height !== hiddenImage.height) {
    fail("CAPTURE_CHANGED", "the two screenshot crops have different dimensions");
  }
  const data = new Uint8ClampedArray(normalImage.data.length);
  for (let index = 0; index < data.length; index += 4) {
    const red = Math.abs(normalImage.data[index] - hiddenImage.data[index]);
    const green = Math.abs(normalImage.data[index + 1] - hiddenImage.data[index + 1]);
    const blue = Math.abs(normalImage.data[index + 2] - hiddenImage.data[index + 2]);
    const active = Math.max(red, green, blue) > 8;
    // The difference supplies only the support mask. Inside that support keep
    // the visible piece RGB so masked photometric matching can compare the
    // original texture to a brightened or darkened target. Zeroing outside
    // prevents the current background under a transparent canvas from
    // becoming a high-confidence false template at x=0.
    data[index] = active ? normalImage.data[index] : 0;
    data[index + 1] = active ? normalImage.data[index + 1] : 0;
    data[index + 2] = active ? normalImage.data[index + 2] : 0;
    // Preserve the changed-pixel support as alpha. The matcher can then
    // recover the actual silhouette instead of correlating a full opaque
    // screenshot rectangle whose unchanged area contains no puzzle signal.
    data[index + 3] = active ? 255 : 0;
  }
  return Object.freeze({ width: normalImage.width, height: normalImage.height, data });
}

async function loadResourceInput(payload, providers) {
  exactObject(payload, ["backgroundUrl", "mode", "puzzleUrl"], "resource capture");
  const [background, puzzle] = await Promise.all([
    decodeImageUrl(payload.backgroundUrl, "background resource", providers),
    decodeImageUrl(payload.puzzleUrl, "puzzle resource", providers),
  ]);
  return Object.freeze({ captureMode: "resource", background, puzzle });
}

async function loadScreenshotInput(payload, providers) {
  exactObject(
    payload,
    ["backgroundRect", "hiddenDataUrl", "mode", "normalDataUrl", "puzzleRect", "viewport"],
    "screenshot capture",
  );
  const viewport = validateViewport(payload.viewport);
  const backgroundRect = validateRect(payload.backgroundRect, "backgroundRect", viewport);
  const puzzleRect = validateRect(payload.puzzleRect, "puzzleRect", viewport);
  const [normal, hidden] = await Promise.all([
    decodeImageUrl(payload.normalDataUrl, "normal screenshot", providers),
    decodeImageUrl(payload.hiddenDataUrl, "hidden screenshot", providers),
  ]);
  if (normal.width !== hidden.width || normal.height !== hidden.height) {
    fail("CAPTURE_CHANGED", "the two screenshots have different dimensions");
  }

  const backgroundPixels = pixelRect(backgroundRect, viewport, hidden);
  const puzzlePixels = pixelRect(puzzleRect, viewport, hidden);
  const background = cropRgba(hidden, backgroundPixels);
  const normalPuzzle = cropRgba(normal, puzzlePixels);
  const hiddenPuzzle = cropRgba(hidden, puzzlePixels);
  const puzzle = differenceRgba(normalPuzzle, hiddenPuzzle);
  return Object.freeze({ captureMode: "screenshot", background, puzzle });
}

export async function loadSolverInput(payload, providers = undefined) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    fail("CAPTURE_INVALID", "capture payload must be an object");
  }
  if (payload.mode === "resource") return loadResourceInput(payload, providers);
  if (payload.mode === "screenshot") return loadScreenshotInput(payload, providers);
  fail("CAPTURE_INVALID", "capture mode must be resource or screenshot");
}
