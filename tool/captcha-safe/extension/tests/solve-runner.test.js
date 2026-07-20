import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";

import {
  captureDetectedCanvases,
  runCaptchaSolve,
  selectDetectedChallenge,
  settleWithin,
  SolverRunError,
} from "../src/solve-runner.js";

const CANVAS_BACKGROUND_DATA_URL = "data:image/png;base64,YmFja2dyb3VuZA==";
const CANVAS_PUZZLE_DATA_URL = "data:image/png;base64,cHV6emxl";

function part(rect, path, resource = undefined) {
  return {
    rect: { ...rect },
    locator: { version: 1, path: [...path] },
    semantic: "slider challenge",
    ...(resource ? { resource: { ...resource } } : {}),
  };
}

function descriptor({ resource = true, pieceLeft = 100, score = 60 } = {}) {
  return {
    version: 1,
    score,
    fingerprint: "detector-fingerprint",
    handle: part({ left: 100, top: 220, width: 40, height: 40 }, [0, 0]),
    track: part({ left: 100, top: 220, width: 300, height: 40 }, [0, 1]),
    background: part(
      { left: 100, top: 50, width: 300, height: 150 },
      [0, 2],
      {
        kind: resource ? "img" : "canvas",
        url: resource ? "https://assets.invalid/background.png" : null,
        naturalWidth: resource ? 600 : null,
        naturalHeight: resource ? 300 : null,
      },
    ),
    piece: part(
      { left: pieceLeft, top: 95, width: 50, height: 50 },
      [0, 3],
      {
        kind: resource ? "img" : "canvas",
        url: resource ? "https://assets.invalid/piece.png" : null,
        naturalWidth: resource ? 100 : null,
        naturalHeight: resource ? 100 : null,
      },
    ),
    viewport: {
      width: 800,
      height: 600,
      devicePixelRatio: 2,
      scrollX: 0,
      scrollY: 0,
    },
  };
}

function solvedResult(captureMode = "resource") {
  return {
    algorithm: "opencv-edge-template-v1",
    confidence: 0.91,
    targetCenter: { x: 300, y: 140 },
    matchBox: { x: 250, y: 90, width: 100, height: 100 },
    background: { width: 600, height: 300 },
    puzzle: { width: 100, height: 100 },
    captureMode,
  };
}

function canvasSolvedResult(captureMode = "resource") {
  return {
    algorithm: "opencv-edge-template-v1",
    confidence: 0.91,
    targetCenter: { x: 150, y: 70 },
    matchBox: { x: 125, y: 45, width: 50, height: 50 },
    background: { width: 300, height: 150 },
    puzzle: { width: 50, height: 50 },
    captureMode,
  };
}

function tallCanvasDescriptor() {
  return {
    version: 1,
    score: 60,
    fingerprint: "tall-canvas-detector-fingerprint",
    handle: part({ left: 32, top: 410, width: 90, height: 90 }, [0, 4, 1]),
    track: part({ left: 32, top: 410, width: 720, height: 90 }, [0, 4]),
    background: part(
      { left: 32, top: 20, width: 720, height: 360 },
      [0, 0],
      { kind: "canvas", url: null, naturalWidth: 720, naturalHeight: 360 },
    ),
    piece: part(
      { left: 32, top: 20, width: 101, height: 360 },
      [0, 2],
      { kind: "canvas", url: null, naturalWidth: 101, naturalHeight: 360 },
    ),
    viewport: {
      width: 900,
      height: 600,
      devicePixelRatio: 1,
      scrollX: 0,
      scrollY: 0,
    },
  };
}

function tallCanvasSolvedResult(captureMode = "resource") {
  return {
    algorithm: "opencv-edge-template-v1",
    confidence: 0.97,
    targetCenter: { x: 390, y: 180 },
    matchBox: { x: 340, y: 0, width: 101, height: 360 },
    background: { width: 720, height: 360 },
    puzzle: { width: 101, height: 360 },
    captureMode,
  };
}

function kgCaptchaDescriptor() {
  return {
    version: 1,
    score: 60,
    fingerprint: "kgcaptcha-detector-fingerprint",
    handle: part({ left: 99, top: 235, width: 52, height: 45 }, [0, 3, 2]),
    track: part({ left: 100, top: 235, width: 360, height: 45 }, [0, 3]),
    background: part(
      { left: 100, top: 40, width: 360, height: 180 },
      [0, 1],
      {
        kind: "css",
        url: "data:image/png;base64,YmFja2dyb3VuZA==",
        naturalWidth: null,
        naturalHeight: null,
      },
    ),
    piece: part(
      { left: 100, top: 40, width: 72, height: 180 },
      [0, 1, 0],
      {
        kind: "img",
        url: "data:image/png;base64,cHV6emxlLXNoYXBl",
        naturalWidth: 72,
        naturalHeight: 180,
      },
    ),
    motion: {
      kind: "linked-offset-left",
      initialHandleOffsetLeft: -1,
      initialPieceOffsetLeft: 0,
    },
    viewport: {
      width: 800,
      height: 600,
      devicePixelRatio: 2,
      scrollX: 0,
      scrollY: 0,
    },
  };
}

function kgCaptchaSolvedResult(captureMode = "resource") {
  return {
    algorithm: "opencv-edge-template-v1",
    confidence: 0.95,
    targetCenter: { x: 158, y: 90 },
    matchBox: { x: 122, y: 0, width: 72, height: 180 },
    background: { width: 360, height: 180 },
    puzzle: { width: 72, height: 180 },
    captureMode,
  };
}

function fakeChrome({
  snapshots = [descriptor(), descriptor(), descriptor()],
  tabUrl = "https://cnse.e-cqs.cn/info-pub/pub/index",
  solverResponses = [solvedResult()],
  screenshotDataUrls = ["data:image/png;base64,normal", "data:image/png;base64,hidden"],
  canvasCaptureResult = {
    ok: true,
    backgroundDataUrl: CANVAS_BACKGROUND_DATA_URL,
    puzzleDataUrl: CANVAS_PUZZLE_DATA_URL,
  },
} = {}) {
  const calls = {
    canvasCaptures: [],
    captures: [],
    debuggerCommands: [],
    debuggerTimeline: [],
    debuggerAttach: 0,
    debuggerDetach: 0,
    dragWaits: [],
    offscreenCreate: 0,
    offscreenClose: 0,
    solverPayloads: [],
    visibility: [],
  };
  let snapshotIndex = 0;
  let screenshotIndex = 0;
  let solverIndex = 0;

  const api = {
    tabs: {
      async query() {
        return [{ id: 7, windowId: 9, url: tabUrl }];
      },
      async captureVisibleTab(windowId, options) {
        calls.captures.push({ windowId, options });
        return screenshotDataUrls[screenshotIndex++] || screenshotDataUrls.at(-1);
      },
    },
    scripting: {
      async executeScript(options) {
        if (options.func.name === "detectPageChallenge") {
          const current = snapshots[Math.min(snapshotIndex, snapshots.length - 1)];
          snapshotIndex += 1;
          return [{
            frameId: 0,
            documentId: "document-1",
            result: { ok: true, descriptor: structuredClone(current) },
          }];
        }
        if (options.func.name === "frameOffsetRelay") {
          return [{
            frameId: 0,
            documentId: "document-1",
            result: {
              token: "top-token",
              offsets: {
                "top-token": { token: "top-token", x: 0, y: 0, scaleX: 1, scaleY: 1 },
              },
              viewport: { width: 800, height: 600, devicePixelRatio: 2 },
            },
          }];
        }
        if (options.func.name === "setDetectedPieceVisibility") {
          calls.visibility.push(options.args[1]);
          return [{ frameId: 0, result: { ok: true, visible: options.args[1] } }];
        }
        if (options.func.name === "captureDetectedCanvases") {
          calls.canvasCaptures.push({
            target: structuredClone(options.target),
            args: structuredClone(options.args),
          });
          return [{
            frameId: options.target.frameIds[0],
            result: structuredClone(canvasCaptureResult),
          }];
        }
        throw new Error(`unexpected injected function: ${options.func.name}`);
      },
    },
    runtime: {
      getURL(path) {
        return `chrome-extension://extension-id/${path}`;
      },
      async getContexts() {
        return [];
      },
      async sendMessage(message) {
        calls.solverPayloads.push(structuredClone(message.payload));
        const configured = solverResponses[Math.min(solverIndex, solverResponses.length - 1)];
        solverIndex += 1;
        if (configured === undefined) return undefined;
        if (configured?.error) {
          return {
            type: "opencv.error",
            requestId: message.requestId,
            error: configured.error,
          };
        }
        return {
          type: "opencv.result",
          requestId: message.requestId,
          result: structuredClone(configured),
        };
      },
    },
    offscreen: {
      async createDocument() {
        calls.offscreenCreate += 1;
      },
      async closeDocument() {
        calls.offscreenClose += 1;
      },
    },
    debugger: {
      async attach() {
        calls.debuggerAttach += 1;
      },
      async sendCommand(target, method, params) {
        const command = { target, method, params: { ...params } };
        calls.debuggerCommands.push(command);
        calls.debuggerTimeline.push({ kind: "event", command });
      },
      async detach() {
        calls.debuggerDetach += 1;
      },
    },
  };
  Object.defineProperty(api, "__captchaSafeDragWaitProviderV1", {
    enumerable: false,
    value: async (milliseconds) => {
      calls.dragWaits.push(milliseconds);
      calls.debuggerTimeline.push({ kind: "wait", milliseconds });
    },
  });
  return { api, calls };
}

test("serialized canvas capture resolves and exports both locators without module closure", () => {
  const exportCalls = [];
  const background = {
    tagName: "CANVAS",
    width: 300,
    height: 150,
    children: [],
    toDataURL(type) {
      exportCalls.push(["background", type]);
      return CANVAS_BACKGROUND_DATA_URL;
    },
  };
  const puzzle = {
    tagName: "CANVAS",
    width: 50,
    height: 50,
    children: [],
    toDataURL(type) {
      exportCalls.push(["puzzle", type]);
      return CANVAS_PUZZLE_DATA_URL;
    },
  };
  const injectedCapture = vm.runInNewContext(
    `(${captureDetectedCanvases.toString()})`,
    { document: { children: [{ children: [background, puzzle] }] } },
  );

  const result = injectedCapture(
    { version: 1, path: [0, 0] },
    { version: 1, path: [0, 1] },
  );
  assert.equal(result.ok, true);
  assert.equal(result.backgroundDataUrl, CANVAS_BACKGROUND_DATA_URL);
  assert.equal(result.puzzleDataUrl, CANVAS_PUZZLE_DATA_URL);
  assert.deepEqual(exportCalls, [
    ["background", "image/png"],
    ["puzzle", "image/png"],
  ]);

  const missing = injectedCapture(
    { version: 1, path: [0, 99] },
    { version: 1, path: [0, 1] },
  );
  assert.equal(missing.ok, false);
  assert.equal(missing.error.code, "CANVAS_NOT_FOUND");
});

test("resource solve validates three snapshots and dispatches exactly fourteen CDP events", async () => {
  const { api, calls } = fakeChrome();
  const result = await runCaptchaSolve(api);

  assert.deepEqual(result, {
    status: "DISPATCHED",
    algorithm: "opencv-edge-template-v1",
    captureMode: "resource",
    confidence: 0.91,
    targetCenter: { x: 300, y: 140 },
    pointerDistancePx: 130,
    eventCount: 14,
  });
  assert.equal(calls.solverPayloads.length, 1);
  assert.deepEqual(calls.solverPayloads[0], {
    mode: "resource",
    backgroundUrl: "https://assets.invalid/background.png",
    puzzleUrl: "https://assets.invalid/piece.png",
  });
  assert.equal(calls.debuggerAttach, 1);
  assert.equal(calls.debuggerDetach, 1);
  assert.equal(calls.debuggerCommands.length, 14);
  assert.equal(calls.debuggerCommands[0].params.type, "mousePressed");
  assert.equal(calls.debuggerCommands.at(-1).params.type, "mouseReleased");
  assert.equal(calls.debuggerCommands.at(-1).params.x, 250);
  assert.equal(calls.debuggerCommands.at(-1).params.y, 240);
  assert.ok(calls.debuggerCommands.every((call) => call.method === "Input.dispatchMouseEvent"));
  const eventFields = {
    mousePressed: ["button", "buttons", "clickCount", "type", "x", "y"],
    mouseMoved: ["button", "buttons", "type", "x", "y"],
    mouseReleased: ["button", "buttons", "clickCount", "type", "x", "y"],
  };
  for (const call of calls.debuggerCommands) {
    assert.deepEqual(Object.keys(call.params).sort(), eventFields[call.params.type]);
    assert.equal(Object.keys(call.params).some((field) => /delay/iu.test(field)), false);
  }
  assert.equal(calls.dragWaits.length, 13);
  assert.ok(calls.dragWaits.every((delay) => Number.isSafeInteger(delay) && delay > 0));
  assert.ok(calls.dragWaits.reduce((sum, delay) => sum + delay, 0) >= 320);
  assert.ok(calls.dragWaits.reduce((sum, delay) => sum + delay, 0) <= 480);
  assert.equal(calls.debuggerTimeline.length, 27);
  for (let index = 0; index < 13; index += 1) {
    assert.equal(calls.debuggerTimeline[index * 2].kind, "event");
    assert.equal(calls.debuggerTimeline[index * 2 + 1].kind, "wait");
  }
  assert.equal(calls.debuggerTimeline.at(-1).kind, "event");
  assert.equal(calls.debuggerTimeline.at(-1).command.params.type, "mouseReleased");
});

test("canvas pair is exported in one injection and solved without visible-page screenshots", async () => {
  const canvasDescriptor = descriptor({ resource: false });
  const { api, calls } = fakeChrome({
    snapshots: [canvasDescriptor, canvasDescriptor, canvasDescriptor],
    solverResponses: [canvasSolvedResult()],
  });
  const result = await runCaptchaSolve(api);

  assert.equal(result.status, "DISPATCHED");
  assert.equal(result.captureMode, "resource");
  assert.equal(result.pointerDistancePx, 130);
  assert.equal(calls.canvasCaptures.length, 1);
  assert.deepEqual(calls.canvasCaptures[0], {
    target: { tabId: 7, frameIds: [0] },
    args: [
      { version: 1, path: [0, 2] },
      { version: 1, path: [0, 3] },
    ],
  });
  assert.deepEqual(calls.solverPayloads, [{
    mode: "resource",
    backgroundUrl: CANVAS_BACKGROUND_DATA_URL,
    puzzleUrl: CANVAS_PUZZLE_DATA_URL,
  }]);
  assert.equal(calls.captures.length, 0);
  assert.deepEqual(calls.visibility, []);
  assert.equal(calls.debuggerCommands.length, 14);
});

test("tall transparent canvas pieces preserve scaled slider geometry", async () => {
  const tallDescriptor = tallCanvasDescriptor();
  const { api, calls } = fakeChrome({
    snapshots: [tallDescriptor, tallDescriptor, tallDescriptor],
    solverResponses: [tallCanvasSolvedResult()],
  });

  const result = await runCaptchaSolve(api);

  assert.equal(result.status, "DISPATCHED");
  assert.equal(result.captureMode, "resource");
  assert.equal(result.pointerDistancePx, 346);
  assert.deepEqual(calls.canvasCaptures, [{
    target: { tabId: 7, frameIds: [0] },
    args: [
      { version: 1, path: [0, 0] },
      { version: 1, path: [0, 2] },
    ],
  }]);
  assert.deepEqual(calls.solverPayloads, [{
    mode: "resource",
    backgroundUrl: CANVAS_BACKGROUND_DATA_URL,
    puzzleUrl: CANVAS_PUZZLE_DATA_URL,
  }]);
  assert.equal(calls.captures.length, 0);
  assert.equal(calls.debuggerCommands.length, 14);
  assert.equal(calls.debuggerCommands.at(-1).params.x, 423);
  assert.equal(calls.debuggerCommands.at(-1).params.y, 455);
});

test("linked full-height image pieces use the captured offsetLeft one-to-one", async () => {
  const kgDescriptor = kgCaptchaDescriptor();
  const { api, calls } = fakeChrome({
    snapshots: [kgDescriptor, kgDescriptor, kgDescriptor],
    solverResponses: [kgCaptchaSolvedResult()],
  });

  const result = await runCaptchaSolve(api);

  assert.equal(result.status, "DISPATCHED");
  assert.equal(result.captureMode, "resource");
  assert.equal(result.pointerDistancePx, 123);
  assert.deepEqual(calls.solverPayloads, [{
    mode: "resource",
    backgroundUrl: "data:image/png;base64,YmFja2dyb3VuZA==",
    puzzleUrl: "data:image/png;base64,cHV6emxlLXNoYXBl",
  }]);
  assert.equal(calls.captures.length, 0);
  assert.equal(calls.debuggerCommands.length, 14);
  assert.equal(calls.debuggerCommands.at(-1).params.x, 248);
  assert.equal(calls.debuggerCommands.at(-1).params.y, 257.5);
});

test("canvas export failure falls back to screenshot diff and restores the piece", async () => {
  const canvasDescriptor = descriptor({ resource: false });
  const { api, calls } = fakeChrome({
    snapshots: [canvasDescriptor, canvasDescriptor, canvasDescriptor],
    canvasCaptureResult: {
      ok: false,
      error: { code: "CANVAS_EXPORT_FAILED", message: "canvas is tainted" },
    },
    solverResponses: [solvedResult("screenshot")],
  });
  const result = await runCaptchaSolve(api);

  assert.equal(result.captureMode, "mixed");
  assert.equal(calls.canvasCaptures.length, 1);
  assert.equal(calls.captures.length, 2);
  assert.deepEqual(calls.visibility, [false, true]);
  assert.deepEqual(calls.solverPayloads, [{
    mode: "screenshot",
    normalDataUrl: "data:image/png;base64,normal",
    hiddenDataUrl: "data:image/png;base64,hidden",
    backgroundRect: { x: 100, y: 50, width: 300, height: 150 },
    puzzleRect: { x: 100, y: 95, width: 50, height: 50 },
    viewport: { width: 800, height: 600 },
  }]);
  assert.equal(calls.debuggerCommands.length, 14);
});

test("canvas resource solve failure retries with screenshot diff", async () => {
  const canvasDescriptor = descriptor({ resource: false });
  const { api, calls } = fakeChrome({
    snapshots: [canvasDescriptor, canvasDescriptor, canvasDescriptor],
    solverResponses: [
      { error: { code: "IMAGE_NO_EDGES", message: "canvas template has no usable edges" } },
      solvedResult("screenshot"),
    ],
  });
  const result = await runCaptchaSolve(api);

  assert.equal(result.captureMode, "mixed");
  assert.equal(calls.canvasCaptures.length, 1);
  assert.equal(calls.solverPayloads.length, 2);
  assert.deepEqual(calls.solverPayloads[0], {
    mode: "resource",
    backgroundUrl: CANVAS_BACKGROUND_DATA_URL,
    puzzleUrl: CANVAS_PUZZLE_DATA_URL,
  });
  assert.equal(calls.solverPayloads[1].mode, "screenshot");
  assert.equal(calls.captures.length, 2);
  assert.deepEqual(calls.visibility, [false, true]);
  assert.equal(calls.debuggerCommands.length, 14);
});

test("resource failure falls back to screenshot diff and always restores the piece", async () => {
  const noResources = descriptor({ resource: true });
  const { api, calls } = fakeChrome({
    snapshots: [noResources, noResources, noResources],
    solverResponses: [
      { error: { code: "IMAGE_FETCH_FAILED", message: "resource unavailable" } },
      solvedResult("screenshot"),
    ],
  });
  const result = await runCaptchaSolve(api);

  assert.equal(result.captureMode, "mixed");
  assert.equal(calls.captures.length, 2);
  assert.deepEqual(calls.visibility, [false, true]);
  assert.deepEqual(calls.solverPayloads[1], {
    mode: "screenshot",
    normalDataUrl: "data:image/png;base64,normal",
    hiddenDataUrl: "data:image/png;base64,hidden",
    backgroundRect: { x: 100, y: 50, width: 300, height: 150 },
    puzzleRect: { x: 100, y: 95, width: 50, height: 50 },
    viewport: { width: 800, height: 600 },
  });
  assert.equal(calls.debuggerCommands.length, 14);
});

test("solver messaging waits for a newly created offscreen document to register", async () => {
  const { api, calls } = fakeChrome({
    solverResponses: [undefined, solvedResult()],
  });
  const result = await runCaptchaSolve(api);
  assert.equal(result.status, "DISPATCHED");
  assert.equal(calls.offscreenCreate, 1);
  assert.equal(calls.solverPayloads.length, 2);
  assert.equal(calls.debuggerCommands.length, 14);
});

test("an unstable pre-capture challenge fails closed before solver or debugger access", async () => {
  const { api, calls } = fakeChrome({
    snapshots: [descriptor(), descriptor({ pieceLeft: 101 })],
  });
  await assert.rejects(
    runCaptchaSolve(api),
    (error) => error instanceof SolverRunError && error.code === "CHALLENGE_CHANGED",
  );
  assert.equal(calls.solverPayloads.length, 0);
  assert.equal(calls.debuggerAttach, 0);
});

test("OpenCV failure never dispatches browser input", async () => {
  const { api, calls } = fakeChrome({
    solverResponses: [{ error: { code: "OPENCV_UNAVAILABLE", message: "runtime unavailable" } }],
  });
  await assert.rejects(
    runCaptchaSolve(api),
    (error) => error instanceof SolverRunError && error.code === "OPENCV_UNAVAILABLE",
  );
  assert.equal(calls.debuggerAttach, 0);
  assert.equal(calls.debuggerCommands.length, 0);
});

test("an invalid success response is rejected before debugger attachment", async () => {
  const invalid = solvedResult();
  invalid.confidence = 0.49;
  const { api, calls } = fakeChrome({ solverResponses: [invalid] });
  await assert.rejects(
    runCaptchaSolve(api),
    (error) => error instanceof SolverRunError && error.code === "SOLVER_PROTOCOL_ERROR",
  );
  assert.equal(calls.debuggerAttach, 0);
  assert.equal(calls.debuggerCommands.length, 0);
});

test("settleWithin preserves an operation result and its original failure", async () => {
  assert.equal(await settleWithin(Promise.resolve("ready"), 100, "TIMEOUT", "too late"), "ready");
  const original = Object.assign(new Error("original failure"), { code: "ORIGINAL" });
  await assert.rejects(
    settleWithin(Promise.reject(original), 100, "TIMEOUT", "too late"),
    (error) => error === original,
  );
});

test("settleWithin validates its timeout before waiting", () => {
  assert.throws(
    () => settleWithin(new Promise(() => {}), 0, "TIMEOUT", "too late"),
    (error) => error instanceof SolverRunError && error.code === "SOLVER_CONFIG_INVALID",
  );
});

test("protected browser pages are rejected before scanning", async () => {
  const { api, calls } = fakeChrome({ tabUrl: "chrome://extensions" });
  await assert.rejects(
    runCaptchaSolve(api),
    (error) => error instanceof SolverRunError && error.code === "ACTIVE_PAGE_PROTECTED",
  );
  assert.equal(calls.debuggerAttach, 0);
  assert.equal(calls.solverPayloads.length, 0);
});

test("other web sites are rejected before scanning", async () => {
  const { api, calls } = fakeChrome({ tabUrl: "https://example.invalid/challenge" });
  await assert.rejects(
    runCaptchaSolve(api),
    (error) => error instanceof SolverRunError && error.code === "SITE_NOT_SUPPORTED",
  );
  assert.equal(calls.debuggerAttach, 0);
  assert.equal(calls.solverPayloads.length, 0);
});

test("a blocking ambiguity in any frame prevents cross-frame candidate selection", () => {
  const detections = [
    {
      frameId: 0,
      result: { ok: false, error: { code: "CHALLENGE_AMBIGUOUS", message: "two candidates" } },
    },
    {
      frameId: 1,
      documentId: "document-2",
      result: { ok: true, descriptor: descriptor() },
    },
  ];
  assert.throws(
    () => selectDetectedChallenge(
      detections,
      new Map([[1, { x: 0, y: 0, scaleX: 1, scaleY: 1 }]]),
      { width: 800, height: 600, devicePixelRatio: 1 },
    ),
    (error) => error instanceof SolverRunError && error.code === "CHALLENGE_AMBIGUOUS",
  );
});
