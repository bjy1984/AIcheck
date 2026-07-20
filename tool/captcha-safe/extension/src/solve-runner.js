import {
  detectPageChallenge,
  setDetectedPieceVisibility,
} from "./challenge-detector.js";
import {
  createCdpDragPlan,
  imageTargetCenterToPointerDistance,
  isChallengeStable,
  sameChallengeIdentity,
  validateGeometryDescriptor,
  validateImageDimensions,
  validateVerticalAlignment,
} from "./solve-geometry.js";

const ALLOWED_SITE_ORIGIN = "https://cnse.e-cqs.cn";
const ALLOWED_SITE_PATH_PREFIX = "/info-pub/";
const WEB_PAGE_PROTOCOLS = new Set(["http:", "https:"]);
const SOLVER_DOCUMENT = "solver/offscreen.html";
const SCREENSHOT_DELAY_MS = 34;
const OFFSCREEN_REASON = "BLOBS";
const OFFSCREEN_RESPONSE_TIMEOUT_MS = 45_000;
const CHROME_API_TIMEOUT_MS = 15_000;
const CLEANUP_TIMEOUT_MS = 2_000;
const INTERNAL_DRAG_WAIT_PROVIDER = "__captchaSafeDragWaitProviderV1";
const RESOURCE_FALLBACK_CODES = new Set([
  "BACKGROUND_SCALE_INVALID",
  "CAPTURE_INVALID",
  "IMAGE_DECODE_FAILED",
  "IMAGE_DIMENSIONS_MISMATCH",
  "IMAGE_FETCH_FAILED",
  "IMAGE_FORMAT_UNSUPPORTED",
  "IMAGE_LIMIT_EXCEEDED",
  "IMAGE_NO_EDGES",
  "MATCH_LOW_CONFIDENCE",
  "MATCH_RESULT_INVALID",
  "OPENCV_MATCH_FAILED",
  "TARGET_CENTER_INVALID",
  "TEMPLATE_TOO_LARGE",
  "TRAVEL_RANGE_INVALID",
  "VERTICAL_ALIGNMENT_MISMATCH",
]);

export class SolverRunError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "SolverRunError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new SolverRunError(code, message);
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export function settleWithin(promise, timeoutMs, code, message) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs <= 0) {
    fail("SOLVER_CONFIG_INVALID", "operation timeout must be a positive integer");
  }
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new SolverRunError(code, message)),
      timeoutMs,
    );
  });
  return Promise.race([Promise.resolve(promise), timeout])
    .finally(() => clearTimeout(timer));
}

function randomId() {
  const bytes = new Uint8Array(18);
  crypto.getRandomValues(bytes);
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export function frameOffsetRelay(nonce) {
  const tokenBytes = new Uint8Array(16);
  crypto.getRandomValues(tokenBytes);
  const token = [...tokenBytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  const offsets = Object.create(null);

  function frameElements(root, output = []) {
    for (const element of root.querySelectorAll("iframe,frame")) output.push(element);
    for (const element of root.querySelectorAll("*")) {
      if (element.shadowRoot) frameElements(element.shadowRoot, output);
    }
    return output;
  }

  return new Promise((resolve) => {
    const handler = (event) => {
      const data = event.data;
      if (!data || data.__captchaSafeFrameOffset !== nonce || typeof data.token !== "string") return;
      const owner = frameElements(document).find((element) => element.contentWindow === event.source);
      if (!owner) return;
      const rect = owner.getBoundingClientRect();
      const outerWidth = owner.offsetWidth || rect.width || 1;
      const outerHeight = owner.offsetHeight || rect.height || 1;
      const ownerScaleX = rect.width / outerWidth;
      const ownerScaleY = rect.height / outerHeight;
      const next = {
        __captchaSafeFrameOffset: nonce,
        token: data.token,
        x: rect.left + owner.clientLeft * ownerScaleX + Number(data.x || 0) * ownerScaleX,
        y: rect.top + owner.clientTop * ownerScaleY + Number(data.y || 0) * ownerScaleY,
        scaleX: Number(data.scaleX || 1) * ownerScaleX,
        scaleY: Number(data.scaleY || 1) * ownerScaleY,
      };
      if (globalThis.top === globalThis) offsets[next.token] = next;
      else globalThis.parent.postMessage(next, "*");
    };
    globalThis.addEventListener("message", handler);
    if (globalThis.top === globalThis) {
      offsets[token] = { token, x: 0, y: 0, scaleX: 1, scaleY: 1 };
    } else {
      setTimeout(() => globalThis.parent.postMessage({
        __captchaSafeFrameOffset: nonce,
        token,
        x: 0,
        y: 0,
        scaleX: 1,
        scaleY: 1,
      }, "*"), 50);
    }
    setTimeout(() => {
      globalThis.removeEventListener("message", handler);
      resolve({
        token,
        offsets: globalThis.top === globalThis ? offsets : null,
        viewport: globalThis.top === globalThis ? {
          width: Number(globalThis.innerWidth),
          height: Number(globalThis.innerHeight),
          devicePixelRatio: Number(globalThis.devicePixelRatio) || 1,
        } : null,
      });
    }, 350);
  });
}

// Passed directly to chrome.scripting.executeScript. Keep this function
// self-contained: Chrome serializes it without this module's lexical scope.
export function captureDetectedCanvases(backgroundLocator, puzzleLocator) {
  const errorResult = (code, message) => ({
    ok: false,
    error: { code, message },
  });

  try {
    const documentObject = globalThis.document;
    if (!documentObject) {
      return errorResult("CANVAS_CAPTURE_UNAVAILABLE", "page document is unavailable");
    }

    const resolveLocator = (locator, role) => {
      if (locator === null || typeof locator !== "object" || locator.version !== 1 ||
          !Array.isArray(locator.path) || locator.path.length > 128) {
        return errorResult("CANVAS_LOCATOR_INVALID", `${role} canvas locator is invalid`);
      }
      let current = documentObject;
      for (const token of locator.path) {
        if (token === "shadow") {
          let shadowRoot = null;
          try {
            shadowRoot = current?.shadowRoot;
          } catch {
            shadowRoot = null;
          }
          if (!shadowRoot) {
            return errorResult(
              "CANVAS_NOT_FOUND",
              `${role} canvas shadow root is no longer available`,
            );
          }
          current = shadowRoot;
        } else if (Number.isSafeInteger(token) && token >= 0) {
          let children;
          try {
            children = current?.children;
          } catch {
            children = null;
          }
          if (!children || token >= children.length) {
            return errorResult("CANVAS_NOT_FOUND", `${role} canvas locator no longer resolves`);
          }
          current = children[token];
        } else {
          return errorResult("CANVAS_LOCATOR_INVALID", `${role} canvas locator path is invalid`);
        }
      }
      return { ok: true, element: current };
    };

    const exportCanvas = (element, role) => {
      const tagName = typeof element?.tagName === "string"
        ? element.tagName.toLowerCase() : "";
      if (tagName !== "canvas" || typeof element?.toDataURL !== "function") {
        return errorResult("CANVAS_ELEMENT_INVALID", `${role} locator does not resolve to a canvas`);
      }
      const width = Number(element.width);
      const height = Number(element.height);
      if (!Number.isSafeInteger(width) || width <= 0 || width > 4096 ||
          !Number.isSafeInteger(height) || height <= 0 || height > 4096) {
        return errorResult(
          "CANVAS_DIMENSIONS_INVALID",
          `${role} canvas dimensions are outside the supported range`,
        );
      }
      let dataUrl;
      try {
        dataUrl = element.toDataURL("image/png");
      } catch {
        return errorResult("CANVAS_EXPORT_FAILED", `${role} canvas could not be exported`);
      }
      if (typeof dataUrl !== "string" ||
          !dataUrl.startsWith("data:image/png;base64,") ||
          dataUrl.length <= "data:image/png;base64,".length) {
        return errorResult("CANVAS_EXPORT_FAILED", `${role} canvas did not produce a PNG image`);
      }
      return { ok: true, dataUrl };
    };

    const background = resolveLocator(backgroundLocator, "background");
    if (!background.ok) return background;
    const puzzle = resolveLocator(puzzleLocator, "puzzle");
    if (!puzzle.ok) return puzzle;
    if (background.element === puzzle.element) {
      return errorResult("CANVAS_ELEMENT_INVALID", "background and puzzle canvases must differ");
    }

    const backgroundImage = exportCanvas(background.element, "background");
    if (!backgroundImage.ok) return backgroundImage;
    const puzzleImage = exportCanvas(puzzle.element, "puzzle");
    if (!puzzleImage.ok) return puzzleImage;
    return {
      ok: true,
      backgroundDataUrl: backgroundImage.dataUrl,
      puzzleDataUrl: puzzleImage.dataUrl,
    };
  } catch (error) {
    const message = typeof error?.message === "string"
      ? error.message.replace(/[\u0000-\u001f\u007f]/gu, " ").slice(0, 160)
      : "unexpected canvas capture failure";
    return errorResult("CANVAS_CAPTURE_FAILED", message || "unexpected canvas capture failure");
  }
}

function transformedRect(rect, transform) {
  if (!rect || !transform || ![rect.left, rect.top, rect.width, rect.height].every(finite)) {
    fail("CHALLENGE_GEOMETRY_INVALID", "challenge geometry is incomplete");
  }
  return Object.freeze({
    left: transform.x + rect.left * transform.scaleX,
    top: transform.y + rect.top * transform.scaleY,
    width: rect.width * transform.scaleX,
    height: rect.height * transform.scaleY,
  });
}

export function transformChallengeDescriptor(descriptor, frameId, documentId, transform) {
  const mapPart = (part) => part ? Object.freeze({
    ...part,
    rect: transformedRect(part.rect, transform),
  }) : null;
  const motion = descriptor.motion?.kind === "linked-offset-left" &&
      finite(descriptor.motion.initialHandleOffsetLeft) &&
      finite(descriptor.motion.initialPieceOffsetLeft)
    ? Object.freeze({
      kind: "linked-offset-left",
      initialHandleOffsetLeft: descriptor.motion.initialHandleOffsetLeft * transform.scaleX,
      initialPieceOffsetLeft: descriptor.motion.initialPieceOffsetLeft * transform.scaleX,
    })
    : null;
  return Object.freeze({
    ...descriptor,
    frameId,
    documentId: typeof documentId === "string" ? documentId : "",
    handle: mapPart(descriptor.handle),
    track: mapPart(descriptor.track),
    background: mapPart(descriptor.background),
    piece: mapPart(descriptor.piece),
    motion,
    frameTransform: Object.freeze({ ...transform }),
  });
}

export function selectDetectedChallenge(detections, frameTransforms, topViewport = null) {
  const blocking = (detections || []).find((injection) =>
    ["CHALLENGE_AMBIGUOUS", "CHALLENGE_SCAN_LIMIT"].includes(injection?.result?.error?.code));
  if (blocking) {
    fail(
      blocking.result.error.code,
      blocking.result.error.message || "the page challenge scan was not conclusive",
    );
  }
  const candidates = [];
  for (const injection of detections || []) {
    if (injection?.result?.ok !== true || !injection.result.descriptor) continue;
    const transform = frameTransforms.get(injection.frameId);
    if (!transform) continue;
    candidates.push(transformChallengeDescriptor(
      injection.result.descriptor,
      injection.frameId,
      injection.documentId,
      transform,
    ));
  }
  candidates.sort((left, right) => Number(right.score || 0) - Number(left.score || 0));
  if (candidates.length === 0) fail("CHALLENGE_NOT_FOUND", "no usable visible slider challenge was found");
  if (candidates.length > 1 &&
      Number(candidates[0].score) - Number(candidates[1].score) <=
        Math.max(3, Number(candidates[0].score) * 0.08)) {
    fail("CHALLENGE_AMBIGUOUS", "multiple slider challenges are equally plausible");
  }
  const selected = candidates[0];
  if (!topViewport || ![topViewport.width, topViewport.height].every(finite) ||
      topViewport.width <= 0 || topViewport.height <= 0) {
    fail("CHALLENGE_GEOMETRY_INVALID", "top-level capture viewport is unavailable");
  }
  return Object.freeze({
    ...selected,
    viewport: Object.freeze({
      width: topViewport.width,
      height: topViewport.height,
      devicePixelRatio: finite(topViewport.devicePixelRatio) && topViewport.devicePixelRatio > 0
        ? topViewport.devicePixelRatio : 1,
    }),
  });
}

export async function detectChallenge(chromeApi, tabId) {
  const [detections, relays] = await Promise.all([
    settleWithin(
      chromeApi.scripting.executeScript({
        target: { tabId, allFrames: true },
        func: detectPageChallenge,
      }),
      CHROME_API_TIMEOUT_MS,
      "CHALLENGE_SCAN_TIMEOUT",
      "the page challenge scan did not finish in time",
    ),
    settleWithin(
      chromeApi.scripting.executeScript({
        target: { tabId, allFrames: true },
        func: frameOffsetRelay,
        args: [randomId()],
      }),
      CHROME_API_TIMEOUT_MS,
      "CHALLENGE_SCAN_TIMEOUT",
      "the page frame scan did not finish in time",
    ),
  ]);
  const tokens = new Map(relays.map((entry) => [entry.result?.token, entry.frameId]));
  const top = relays.find((entry) => entry.frameId === 0)?.result?.offsets || {};
  const topViewport = relays.find((entry) => entry.frameId === 0)?.result?.viewport || null;
  const transforms = new Map();
  for (const [token, transform] of Object.entries(top)) {
    const frameId = tokens.get(token);
    if (Number.isInteger(frameId)) transforms.set(frameId, transform);
  }
  return selectDetectedChallenge(detections, transforms, topViewport);
}

function resourceUrl(part) {
  const value = part?.resource?.url;
  if (typeof value !== "string" || !value) return null;
  try {
    const parsed = new URL(value);
    return ["https:", "http:", "data:"].includes(parsed.protocol) ? value : null;
  } catch {
    return null;
  }
}

async function setPieceVisibility(
  chromeApi,
  tabId,
  descriptor,
  visible,
  timeoutMs = CHROME_API_TIMEOUT_MS,
) {
  const locator = descriptor.piece?.locator;
  if (!locator) fail("SCREENSHOT_CAPTURE_UNAVAILABLE", "the detected puzzle layer cannot be isolated");
  const response = await settleWithin(
    chromeApi.scripting.executeScript({
      target: { tabId, frameIds: [descriptor.frameId] },
      func: setDetectedPieceVisibility,
      args: [locator, visible],
    }),
    timeoutMs,
    "SCREENSHOT_CAPTURE_TIMEOUT",
    "the puzzle layer update did not finish in time",
  );
  if (response?.[0]?.result?.ok !== true) {
    fail("SCREENSHOT_CAPTURE_UNAVAILABLE", "the detected puzzle layer could not be isolated");
  }
}

async function screenshotSources(chromeApi, tab, descriptor) {
  const normalDataUrl = await settleWithin(
    chromeApi.tabs.captureVisibleTab(tab.windowId, { format: "png" }),
    CHROME_API_TIMEOUT_MS,
    "SCREENSHOT_CAPTURE_TIMEOUT",
    "the visible page capture did not finish in time",
  );
  let hidden = false;
  try {
    await setPieceVisibility(chromeApi, tab.id, descriptor, false);
    hidden = true;
    await wait(SCREENSHOT_DELAY_MS);
    const hiddenDataUrl = await settleWithin(
      chromeApi.tabs.captureVisibleTab(tab.windowId, { format: "png" }),
      CHROME_API_TIMEOUT_MS,
      "SCREENSHOT_CAPTURE_TIMEOUT",
      "the background capture did not finish in time",
    );
    return {
      mode: "screenshot",
      normalDataUrl,
      hiddenDataUrl,
      backgroundRect: {
        x: descriptor.background.rect.left,
        y: descriptor.background.rect.top,
        width: descriptor.background.rect.width,
        height: descriptor.background.rect.height,
      },
      puzzleRect: {
        x: descriptor.piece.rect.left,
        y: descriptor.piece.rect.top,
        width: descriptor.piece.rect.width,
        height: descriptor.piece.rect.height,
      },
      viewport: {
        width: descriptor.viewport.width,
        height: descriptor.viewport.height,
      },
    };
  } finally {
    if (hidden) {
      try {
        await setPieceVisibility(chromeApi, tab.id, descriptor, true, CLEANUP_TIMEOUT_MS);
      } catch { /* best effort */ }
    }
  }
}

function resourceSources(descriptor) {
  const backgroundUrl = resourceUrl(descriptor.background);
  const puzzleUrl = resourceUrl(descriptor.piece);
  if (backgroundUrl && puzzleUrl) {
    return { mode: "resource", backgroundUrl, puzzleUrl };
  }
  return null;
}

function usesCanvasPair(descriptor) {
  return descriptor.background?.resource?.kind === "canvas" &&
    descriptor.piece?.resource?.kind === "canvas";
}

async function canvasSources(chromeApi, tabId, descriptor) {
  const backgroundLocator = descriptor.background?.locator;
  const puzzleLocator = descriptor.piece?.locator;
  if (!backgroundLocator || !puzzleLocator) {
    fail("CANVAS_CAPTURE_UNAVAILABLE", "the detected canvases cannot be located");
  }
  const response = await settleWithin(
    chromeApi.scripting.executeScript({
      target: { tabId, frameIds: [descriptor.frameId] },
      func: captureDetectedCanvases,
      args: [backgroundLocator, puzzleLocator],
    }),
    CHROME_API_TIMEOUT_MS,
    "CANVAS_CAPTURE_TIMEOUT",
    "the canvas capture did not finish in time",
  );
  const result = response?.[0]?.result;
  if (result?.ok !== true) {
    const message = typeof result?.error?.message === "string"
      ? result.error.message : "the detected canvases could not be captured";
    fail("CANVAS_CAPTURE_UNAVAILABLE", message);
  }
  const prefix = "data:image/png;base64,";
  if (typeof result.backgroundDataUrl !== "string" ||
      !result.backgroundDataUrl.startsWith(prefix) ||
      result.backgroundDataUrl.length <= prefix.length ||
      typeof result.puzzleDataUrl !== "string" ||
      !result.puzzleDataUrl.startsWith(prefix) ||
      result.puzzleDataUrl.length <= prefix.length) {
    fail("CANVAS_CAPTURE_UNAVAILABLE", "the canvas capture response is invalid");
  }
  return {
    mode: "resource",
    backgroundUrl: result.backgroundDataUrl,
    puzzleUrl: result.puzzleDataUrl,
  };
}

async function ensureOffscreenDocument(chromeApi) {
  const url = chromeApi.runtime.getURL(SOLVER_DOCUMENT);
  const contexts = typeof chromeApi.runtime.getContexts === "function"
    ? await settleWithin(
      chromeApi.runtime.getContexts({
        contextTypes: ["OFFSCREEN_DOCUMENT"],
        documentUrls: [url],
      }),
      CHROME_API_TIMEOUT_MS,
      "OPENCV_UNAVAILABLE",
      "the local OpenCV document lookup did not finish in time",
    )
    : [];
  if (contexts.length === 0) {
    await settleWithin(
      chromeApi.offscreen.createDocument({
        url: SOLVER_DOCUMENT,
        reasons: [OFFSCREEN_REASON],
        justification: "Decode user-triggered puzzle image blobs and run packaged OpenCV WASM",
      }),
      CHROME_API_TIMEOUT_MS,
      "OPENCV_UNAVAILABLE",
      "the local OpenCV document did not open in time",
    );
  }
}

export async function solveWithOffscreen(chromeApi, sources) {
  const requestId = randomId();
  let response;
  try {
    await ensureOffscreenDocument(chromeApi);
    const request = {
      target: "opencv-offscreen",
      type: "opencv.solve",
      requestId,
      payload: sources,
    };
    const deadline = Date.now() + OFFSCREEN_RESPONSE_TIMEOUT_MS;
    let lastError = null;
    while (Date.now() < deadline) {
      try {
        response = await settleWithin(
          chromeApi.runtime.sendMessage(request),
          Math.max(1, deadline - Date.now()),
          "OPENCV_UNAVAILABLE",
          "the local OpenCV solve did not finish in time",
        );
        if (response !== undefined) break;
      } catch (error) {
        lastError = error;
      }
      await wait(50);
    }
    if (response === undefined) {
      fail(
        "OPENCV_UNAVAILABLE",
        lastError?.message || "the local OpenCV document did not become ready",
      );
    }
  } finally {
    if (typeof chromeApi.offscreen.closeDocument === "function") {
      try {
        await settleWithin(
          chromeApi.offscreen.closeDocument(),
          CLEANUP_TIMEOUT_MS,
          "OPENCV_CLEANUP_TIMEOUT",
          "the local OpenCV document did not close in time",
        );
      } catch { /* best effort */ }
    }
  }
  if (!response || response.requestId !== requestId) {
    fail("SOLVER_PROTOCOL_ERROR", "OpenCV solver returned an invalid response");
  }
  if (response.type === "opencv.error") {
    fail(response.error?.code || "SOLVER_FAILED", response.error?.message || "OpenCV solve failed");
  }
  if (response.type !== "opencv.result" || !response.result) {
    fail("SOLVER_PROTOCOL_ERROR", "OpenCV solver response type is invalid");
  }
  return validateSolverResult(response.result, sources.mode);
}

function positiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function exactFields(value, fields) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...fields].sort();
  return actual.length === expected.length &&
    actual.every((field, index) => field === expected[index]);
}

export function validateSolverResult(value, expectedCaptureMode) {
  if (!exactFields(value, [
    "algorithm",
    "background",
    "captureMode",
    "confidence",
    "matchBox",
    "puzzle",
    "targetCenter",
  ]) || value.algorithm !== "opencv-edge-template-v1" ||
      value.captureMode !== expectedCaptureMode ||
      typeof value.confidence !== "number" || !Number.isFinite(value.confidence) ||
      value.confidence < 0.5 || value.confidence > 1 ||
      !exactFields(value.background, ["height", "width"]) ||
      !exactFields(value.puzzle, ["height", "width"]) ||
      !exactFields(value.targetCenter, ["x", "y"]) ||
      !exactFields(value.matchBox, ["height", "width", "x", "y"])) {
    fail("SOLVER_PROTOCOL_ERROR", "OpenCV solver result schema is invalid");
  }
  const { background, puzzle, targetCenter, matchBox } = value;
  if (![background.width, background.height, puzzle.width, puzzle.height].every(positiveInteger) ||
      background.width > 4096 || background.height > 4096 ||
      puzzle.width > background.width || puzzle.height > background.height ||
      !Number.isSafeInteger(matchBox.x) || !Number.isSafeInteger(matchBox.y) ||
      matchBox.x < 0 || matchBox.y < 0 ||
      matchBox.width !== puzzle.width || matchBox.height !== puzzle.height ||
      matchBox.x + matchBox.width > background.width ||
      matchBox.y + matchBox.height > background.height ||
      !Number.isSafeInteger(targetCenter.x) || !Number.isSafeInteger(targetCenter.y) ||
      targetCenter.x !== matchBox.x + Math.floor(matchBox.width / 2) ||
      targetCenter.y !== matchBox.y + Math.floor(matchBox.height / 2)) {
    fail("SOLVER_PROTOCOL_ERROR", "OpenCV solver result geometry is invalid");
  }
  return Object.freeze({
    algorithm: value.algorithm,
    confidence: value.confidence,
    targetCenter: Object.freeze({ ...targetCenter }),
    matchBox: Object.freeze({ ...matchBox }),
    background: Object.freeze({ ...background }),
    puzzle: Object.freeze({ ...puzzle }),
    captureMode: value.captureMode,
  });
}

function partIdentity(descriptor, part, role) {
  const resource = part?.resource || {};
  const locator = Array.isArray(part?.locator?.path) ? part.locator.path : [];
  return JSON.stringify([
    "challenge-part-v1",
    descriptor.frameId,
    descriptor.documentId || "",
    role,
    locator,
    resource.kind || "none",
    resource.url || "",
    resource.naturalWidth || 0,
    resource.naturalHeight || 0,
  ]);
}

export function canonicalGeometry(descriptor, solved) {
  const background = descriptor.background.rect;
  const puzzle = descriptor.piece.rect;
  const track = descriptor.track.rect;
  const handle = descriptor.handle.rect;
  const linkedOffsetMotion = descriptor.motion?.kind === "linked-offset-left" &&
    finite(descriptor.motion.initialHandleOffsetLeft) &&
    finite(descriptor.motion.initialPieceOffsetLeft);
  return {
    frameId: descriptor.frameId,
    backgroundIdentity: partIdentity(descriptor, descriptor.background, "background"),
    puzzleIdentity: partIdentity(descriptor, descriptor.piece, "piece"),
    movementModel: linkedOffsetMotion ? "linked-offset-left" : "scaled-ranges",
    initialHandleOffsetLeft: linkedOffsetMotion
      ? descriptor.motion.initialHandleOffsetLeft
      : 0,
    handle,
    track,
    geometry: {
      backgroundLeft: background.left,
      backgroundTop: background.top,
      backgroundWidth: background.width,
      backgroundHeight: background.height,
      backgroundNaturalWidth: solved.background.width,
      backgroundNaturalHeight: solved.background.height,
      puzzleLeft: puzzle.left,
      puzzleTop: puzzle.top,
      puzzleWidth: puzzle.width,
      puzzleHeight: puzzle.height,
      trackWidth: track.width,
      sliderWidth: handle.width,
      devicePixelRatio: descriptor.viewport?.devicePixelRatio || 1,
    },
  };
}

function solveGeometry(descriptor, solved) {
  const geometryDescriptor = canonicalGeometry(descriptor, solved);
  const geometry = validateGeometryDescriptor(geometryDescriptor);
  validateImageDimensions(solved, geometry);
  validateVerticalAlignment(solved.targetCenter.y, geometry);
  const pointerDistance = imageTargetCenterToPointerDistance(solved.targetCenter.x, geometry);
  return Object.freeze({ geometryDescriptor, pointerDistance, solved });
}

function resourceFallbackAllowed(error) {
  return typeof error?.code === "string" && RESOURCE_FALLBACK_CODES.has(error.code);
}

async function captureSolveAndValidate(chromeApi, tab, descriptor) {
  const canvasPair = usesCanvasPair(descriptor);
  let direct = null;
  if (canvasPair) {
    try {
      direct = await canvasSources(chromeApi, tab.id, descriptor);
    } catch {
      // A tainted, replaced, or otherwise unreadable canvas can still be
      // handled by the visible-page screenshot path below.
    }
  } else {
    direct = resourceSources(descriptor);
  }
  if (direct) {
    try {
      return Object.freeze({
        ...solveGeometry(descriptor, await solveWithOffscreen(chromeApi, direct)),
        captureMode: "resource",
      });
    } catch (error) {
      if (!resourceFallbackAllowed(error)) throw error;
    }
  }

  const screenshot = await screenshotSources(chromeApi, tab, descriptor);
  return Object.freeze({
    ...solveGeometry(descriptor, await solveWithOffscreen(chromeApi, screenshot)),
    captureMode: direct || canvasPair ? "mixed" : "screenshot",
  });
}

function provisionalGeometry(descriptor) {
  return canonicalGeometry(descriptor, {
    background: { width: 1, height: 1 },
    puzzle: { width: 1, height: 1 },
  });
}

async function dispatchDrag(chromeApi, tabId, plan, waitProvider = wait) {
  const target = { tabId };
  let attached = false;
  try {
    await settleWithin(
      chromeApi.debugger.attach(target, "1.3"),
      CHROME_API_TIMEOUT_MS,
      "DRAG_DISPATCH_TIMEOUT",
      "browser input attachment did not finish in time",
    );
    attached = true;
    for (let index = 0; index < plan.events.length; index += 1) {
      await settleWithin(
        chromeApi.debugger.sendCommand(
          target,
          "Input.dispatchMouseEvent",
          plan.events[index],
        ),
        CHROME_API_TIMEOUT_MS,
        "DRAG_DISPATCH_TIMEOUT",
        "browser drag dispatch did not finish in time",
      );
      const delayMs = plan.delaysMs[index];
      if (delayMs > 0) await waitProvider(delayMs);
    }
  } catch (error) {
    fail("DRAG_DISPATCH_FAILED", error?.message || "browser drag dispatch failed");
  } finally {
    if (attached) {
      try {
        await settleWithin(
          chromeApi.debugger.detach(target),
          CLEANUP_TIMEOUT_MS,
          "DRAG_CLEANUP_TIMEOUT",
          "browser input detachment did not finish in time",
        );
      } catch { /* best effort */ }
    }
  }
}

function assertApi(chromeApi) {
  const required = [
    chromeApi?.tabs?.query,
    chromeApi?.tabs?.captureVisibleTab,
    chromeApi?.scripting?.executeScript,
    chromeApi?.debugger?.attach,
    chromeApi?.debugger?.sendCommand,
    chromeApi?.debugger?.detach,
    chromeApi?.offscreen?.createDocument,
  ];
  if (required.some((value) => typeof value !== "function")) {
    fail("EXTENSION_API_UNAVAILABLE", "required Chrome extension APIs are unavailable");
  }
}

export async function runCaptchaSolve(chromeApi) {
  assertApi(chromeApi);
  const tabs = await settleWithin(
    chromeApi.tabs.query({ active: true, currentWindow: true }),
    CHROME_API_TIMEOUT_MS,
    "ACTIVE_PAGE_TIMEOUT",
    "the active page lookup did not finish in time",
  );
  const tab = tabs[0];
  if (!Number.isInteger(tab?.id) || !Number.isInteger(tab?.windowId) || typeof tab.url !== "string") {
    fail("ACTIVE_PAGE_NOT_FOUND", "no active web page was found");
  }
  let url;
  try { url = new URL(tab.url); } catch { fail("ACTIVE_PAGE_INVALID", "active tab URL is invalid"); }
  if (!WEB_PAGE_PROTOCOLS.has(url.protocol)) {
    fail("ACTIVE_PAGE_PROTECTED", "Chrome does not allow extensions to control this page");
  }
  if (url.origin !== ALLOWED_SITE_ORIGIN || !url.pathname.startsWith(ALLOWED_SITE_PATH_PREFIX)) {
    fail("SITE_NOT_SUPPORTED", "请在全国特种设备公示信息查询平台页面上使用此扩展");
  }

  const first = await detectChallenge(chromeApi, tab.id);
  const stable = await detectChallenge(chromeApi, tab.id);
  const firstProvisional = provisionalGeometry(first);
  const stableProvisional = provisionalGeometry(stable);
  if (!sameChallengeIdentity(firstProvisional, stableProvisional) ||
      !isChallengeStable(firstProvisional, stableProvisional)) {
    fail("CHALLENGE_CHANGED", "the slider challenge was not stable before capture");
  }

  const recognized = await captureSolveAndValidate(chromeApi, tab, stable);
  const finalSnapshot = await detectChallenge(chromeApi, tab.id);
  const finalGeometry = canonicalGeometry(finalSnapshot, recognized.solved);
  if (!sameChallengeIdentity(recognized.geometryDescriptor, finalGeometry) ||
      !isChallengeStable(recognized.geometryDescriptor, finalGeometry)) {
    fail("CHALLENGE_CHANGED", "the slider challenge changed before the drag");
  }
  const seedWords = new Uint32Array(1);
  crypto.getRandomValues(seedWords);
  const plan = createCdpDragPlan(
    finalGeometry.handle,
    recognized.pointerDistance,
    seedWords[0],
  );
  const waitProvider = typeof chromeApi[INTERNAL_DRAG_WAIT_PROVIDER] === "function"
    ? chromeApi[INTERNAL_DRAG_WAIT_PROVIDER] : wait;
  await dispatchDrag(chromeApi, tab.id, plan, waitProvider);
  return Object.freeze({
    status: "DISPATCHED",
    algorithm: "opencv-edge-template-v1",
    captureMode: recognized.captureMode,
    confidence: recognized.solved.confidence,
    targetCenter: Object.freeze({ ...recognized.solved.targetCenter }),
    pointerDistancePx: recognized.pointerDistance,
    eventCount: plan.events.length,
  });
}
