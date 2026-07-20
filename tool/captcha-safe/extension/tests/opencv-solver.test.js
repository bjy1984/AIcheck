import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import {
  cropRgba,
  differenceRgba,
  loadSolverInput,
} from "../solver/image-input.js";
import {
  OpenCvSolverError,
  solvePuzzleImages,
  waitForOpenCvRuntime,
} from "../solver/opencv-solver.js";

const extensionRoot = new URL("../", import.meta.url);

function rgba(width, height, value = 32) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let offset = 0; offset < data.length; offset += 4) {
    data[offset] = value;
    data[offset + 1] = value + 1;
    data[offset + 2] = value + 2;
    data[offset + 3] = 255;
  }
  return { width, height, data };
}

function fakeOpenCv({ edgePixels = true, confidence = 0.91, maxLoc = { x: 12, y: 4 } } = {}) {
  const calls = [];
  const mats = [];
  class Mat {
    constructor(rows = 0, cols = 0) {
      this.rows = rows;
      this.cols = cols;
      this.data = new Uint8Array(rows * cols * 4);
      this.deleted = false;
      mats.push(this);
    }

    delete() {
      assert.equal(this.deleted, false, "a Mat must be deleted exactly once");
      this.deleted = true;
    }
  }
  const cv = {
    CV_8UC4: 24,
    COLOR_RGBA2GRAY: 11,
    TM_CCOEFF_NORMED: 5,
    Mat,
    cvtColor(source, destination, code, channels) {
      calls.push({ name: "cvtColor", code, channels });
      destination.rows = source.rows;
      destination.cols = source.cols;
      destination.data = new Uint8Array(source.rows * source.cols).fill(127);
    },
    Canny(source, destination, low, high, aperture, l2gradient) {
      calls.push({ name: "Canny", low, high, aperture, l2gradient });
      destination.rows = source.rows;
      destination.cols = source.cols;
      destination.data = new Uint8Array(source.rows * source.cols);
      if (edgePixels) destination.data[Math.min(1, destination.data.length - 1)] = 255;
    },
    matchTemplate(background, puzzle, destination, method) {
      calls.push({ name: "matchTemplate", method });
      destination.rows = background.rows - puzzle.rows + 1;
      destination.cols = background.cols - puzzle.cols + 1;
      destination.data = new Uint8Array(Math.max(1, destination.rows * destination.cols)).fill(1);
    },
    minMaxLoc() {
      calls.push({ name: "minMaxLoc" });
      return { minVal: -0.2, maxVal: confidence, minLoc: { x: 0, y: 0 }, maxLoc };
    },
  };
  return { cv, calls, mats };
}

test("bundled OpenCV 4.13.0 artifact matches its immutable local lock", async () => {
  const artifact = await readFile(new URL("vendor/opencv/opencv.js", extensionRoot));
  const license = await readFile(new URL("vendor/opencv/LICENSE", extensionRoot));
  const lock = JSON.parse(await readFile(new URL("vendor/opencv/lock.json", extensionRoot), "utf8"));
  const patchScript = await readFile(new URL("vendor/opencv/patch-mv3.mjs", extensionRoot), "utf8");
  assert.equal(lock.version, "4.13.0");
  assert.equal(lock.artifactBytes, artifact.byteLength);
  assert.equal(createHash("sha256").update(artifact).digest("hex"), lock.artifactSha256);
  assert.equal(createHash("sha256").update(license).digest("hex"), lock.licenseSha256);
  assert.equal(lock.embeddedWasm, true);
  assert.equal(lock.remoteCodeRequiredAtRuntime, false);
  assert.equal(lock.dynamicJavascriptExecution, false);
  assert.equal(lock.patchScript, "patch-mv3.mjs");
  assert.match(lock.upstreamArtifactSha256, /^[a-f0-9]{64}$/u);
  assert.ok(Number.isSafeInteger(lock.upstreamArtifactBytes) && lock.upstreamArtifactBytes > 0);
  assert.ok(patchScript.includes(lock.upstreamArtifactSha256));
  assert.ok(patchScript.includes(lock.artifactSha256));
  assert.equal([...patchScript.matchAll(/\blabel:/gu)].length, lock.patchCount);
  const artifactText = artifact.toString("utf8");
  assert.match(
    artifactText.slice(0, 30_000),
    /data:application\/octet-stream;base64,AGFzbQE/u,
  );
  assert.doesNotMatch(artifactText, /\b(?:eval|Function)\s*\(/u);
  assert.doesNotMatch(artifactText, /\bnew_\s*\(\s*Function\b/u);
  assert.doesNotMatch(artifactText, /\bnew_\s*\(\s*Function\s*,/u);
  assert.doesNotMatch(artifactText, /https?:\/\//u);
  assert.match(artifactText, /wasmBinaryFile="data:application\/octet-stream;base64,/u);
});

test("offscreen page loads the bundled classic runtime before the module adapter", async () => {
  const html = await readFile(new URL("solver/offscreen.html", extensionRoot), "utf8");
  const adapter = await readFile(new URL("solver/offscreen.js", extensionRoot), "utf8");
  const runtimePosition = html.indexOf("../vendor/opencv/opencv.js");
  const adapterPosition = html.indexOf("offscreen.js");
  assert.ok(runtimePosition >= 0);
  assert.ok(adapterPosition > runtimePosition);
  assert.doesNotMatch(html, /https?:\/\//u);
  assert.match(adapter, /message\.target !== "opencv-offscreen"/u);
});

test("patched OpenCV runtime executes with string code generation blocked", async () => {
  const artifact = await readFile(new URL("vendor/opencv/opencv.js", extensionRoot), "utf8");
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    performance,
    atob,
    document: { currentScript: null, title: "" },
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  const context = vm.createContext(sandbox, {
    codeGeneration: {
      strings: false,
      wasm: true,
    },
  });
  assert.throws(
    () => vm.runInContext("eval('1 + 1')", context),
    /Code generation from strings disallowed/u,
  );
  assert.throws(
    () => vm.runInContext("new Function('return 1')", context),
    /Code generation from strings disallowed/u,
  );
  assert.equal(
    vm.runInContext(
      "WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0]))",
      context,
    ),
    true,
  );
  vm.runInContext(artifact, context, { filename: "opencv.js" });
  await new Promise((resolve) => sandbox.cv.then(() => resolve()));

  const result = vm.runInContext(`(() => {
    const backgroundWidth = 64;
    const backgroundHeight = 40;
    const puzzleWidth = 15;
    const puzzleHeight = 13;
    const expectedLeft = 27;
    const expectedTop = 12;
    const background = new cv.Mat(backgroundHeight, backgroundWidth, cv.CV_8UC4);
    const puzzle = new cv.Mat(puzzleHeight, puzzleWidth, cv.CV_8UC4);
    for (let y = 0; y < backgroundHeight; y += 1) {
      for (let x = 0; x < backgroundWidth; x += 1) {
        const offset = (y * backgroundWidth + x) * 4;
        background.data[offset] = 128;
        background.data[offset + 1] = 128;
        background.data[offset + 2] = 128;
        background.data[offset + 3] = 255;
      }
    }
    for (let y = 0; y < puzzleHeight; y += 1) {
      for (let x = 0; x < puzzleWidth; x += 1) {
        const value = x === 0 || y === 0 || x === puzzleWidth - 1 || y === puzzleHeight - 1
          ? 128
          : 24 + ((x * 37 + y * 53 + x * y * 11 + (x ^ y) * 17) % 208);
        const sourceOffset = (y * puzzleWidth + x) * 4;
        puzzle.data[sourceOffset] = value;
        puzzle.data[sourceOffset + 1] = value;
        puzzle.data[sourceOffset + 2] = value;
        puzzle.data[sourceOffset + 3] = 255;
        const destinationOffset = ((expectedTop + y) * backgroundWidth + expectedLeft + x) * 4;
        background.data[destinationOffset] = value;
        background.data[destinationOffset + 1] = value;
        background.data[destinationOffset + 2] = value;
      }
    }
    const backgroundGray = new cv.Mat();
    const puzzleGray = new cv.Mat();
    const backgroundEdges = new cv.Mat();
    const puzzleEdges = new cv.Mat();
    const correlation = new cv.Mat();
    cv.cvtColor(background, backgroundGray, cv.COLOR_RGBA2GRAY, 0);
    cv.cvtColor(puzzle, puzzleGray, cv.COLOR_RGBA2GRAY, 0);
    cv.Canny(backgroundGray, backgroundEdges, 50, 150, 3, false);
    cv.Canny(puzzleGray, puzzleEdges, 50, 150, 3, false);
    cv.matchTemplate(backgroundEdges, puzzleEdges, correlation, cv.TM_CCOEFF_NORMED);
    const match = cv.minMaxLoc(correlation);
    const output = { x: match.maxLoc.x, y: match.maxLoc.y, confidence: match.maxVal };
    for (const mat of [correlation, puzzleEdges, backgroundEdges, puzzleGray, backgroundGray, puzzle, background]) {
      mat.delete();
    }
    return output;
  })()`, context);
  assert.equal(result.x, 27);
  assert.equal(result.y, 12);
  assert.ok(result.confidence >= 0.99999);
});

test("solver runs RGBA to gray, Canny, and normalized template matching", () => {
  const fake = fakeOpenCv();
  const result = solvePuzzleImages({
    background: rgba(40, 20),
    puzzle: rgba(5, 3),
  }, fake.cv);

  assert.deepEqual(result, {
    algorithm: "opencv-edge-template-v1",
    confidence: 0.91,
    targetCenter: { x: 14, y: 5 },
    matchBox: { x: 12, y: 4, width: 5, height: 3 },
    background: { width: 40, height: 20 },
    puzzle: { width: 5, height: 3 },
  });
  assert.deepEqual(
    fake.calls.filter((call) => call.name === "Canny"),
    [
      { name: "Canny", low: 50, high: 150, aperture: 3, l2gradient: false },
      { name: "Canny", low: 50, high: 150, aperture: 3, l2gradient: false },
    ],
  );
  assert.deepEqual(
    fake.calls.map((call) => call.name),
    ["cvtColor", "Canny", "cvtColor", "Canny", "matchTemplate", "minMaxLoc"],
  );
  assert.equal(fake.calls.at(-2).method, fake.cv.TM_CCOEFF_NORMED);
  assert.equal(fake.mats.length, 7);
  assert.ok(fake.mats.every((mat) => mat.deleted));
});

test("solver abstains on low confidence, missing edges, and invalid image bounds", () => {
  const low = fakeOpenCv({ confidence: 0.499 });
  assert.throws(
    () => solvePuzzleImages({ background: rgba(20, 10), puzzle: rgba(4, 4) }, low.cv),
    (error) => error instanceof OpenCvSolverError && error.code === "MATCH_LOW_CONFIDENCE",
  );
  assert.ok(low.mats.every((mat) => mat.deleted));

  const flat = fakeOpenCv({ edgePixels: false });
  assert.throws(
    () => solvePuzzleImages({ background: rgba(20, 10), puzzle: rgba(4, 4) }, flat.cv),
    (error) => error instanceof OpenCvSolverError && error.code === "IMAGE_NO_EDGES",
  );
  assert.ok(flat.mats.every((mat) => mat.deleted));

  const validCv = fakeOpenCv().cv;
  assert.throws(
    () => solvePuzzleImages({ background: rgba(4, 4), puzzle: rgba(5, 2) }, validCv),
    (error) => error.code === "TEMPLATE_TOO_LARGE",
  );
  assert.throws(
    () => solvePuzzleImages({
      background: { width: 4_097, height: 1, data: new Uint8Array() },
      puzzle: rgba(1, 1),
    }, validCv),
    (error) => error.code === "IMAGE_LIMIT_EXCEEDED",
  );
});

test("OpenCV thenable readiness is awaited without resolving with the thenable", async () => {
  const runtime = {};
  runtime.then = (callback) => {
    runtime.calledRun = true;
    runtime.CV_8UC4 = 24;
    runtime.COLOR_RGBA2GRAY = 11;
    runtime.TM_CCOEFF_NORMED = 5;
    runtime.Mat = class {};
    runtime.cvtColor = () => {};
    runtime.Canny = () => {};
    runtime.matchTemplate = () => {};
    runtime.minMaxLoc = () => {};
    queueMicrotask(() => callback(runtime));
    return runtime;
  };
  const ready = await waitForOpenCvRuntime(runtime, { timeoutMs: 1_000 });
  assert.equal(ready.runtime, runtime);
  assert.equal(typeof runtime.Mat, "function");
});

test("OpenCV readiness accepts a distinct resolved module and waits for late bindings", async () => {
  const resolved = {};
  const placeholder = {
    then(callback) {
      queueMicrotask(() => {
        callback(resolved);
        setTimeout(() => {
          resolved.CV_8UC4 = 24;
          resolved.COLOR_RGBA2GRAY = 11;
          resolved.TM_CCOEFF_NORMED = 5;
          resolved.Mat = class {};
          resolved.cvtColor = () => {};
          resolved.Canny = () => {};
          resolved.matchTemplate = () => {};
          resolved.minMaxLoc = () => {};
        }, 10);
      });
      return placeholder;
    },
  };
  const ready = await waitForOpenCvRuntime(placeholder, { timeoutMs: 1_000 });
  assert.equal(ready.runtime, resolved);
});

test("screenshot capture crops the hidden background and differences the puzzle", async () => {
  const normal = rgba(4, 4, 10);
  const hidden = rgba(4, 4, 10);
  for (let y = 1; y < 3; y += 1) {
    for (let x = 1; x < 3; x += 1) {
      const offset = (y * 4 + x) * 4;
      normal.data[offset] = 90;
      normal.data[offset + 1] = 70;
      normal.data[offset + 2] = 50;
    }
  }
  const pngHeader = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  const encoded = new Map([
    ["https://example.test/normal.png", new Uint8Array([...pngHeader, 1])],
    ["https://example.test/hidden.png", new Uint8Array([...pngHeader, 2])],
  ]);
  const bitmaps = new Map([[1, normal], [2, hidden]]);
  const providers = {
    async fetchProvider(url) {
      const bytes = encoded.get(url);
      return {
        ok: Boolean(bytes),
        headers: { get: () => String(bytes?.byteLength ?? 0) },
        body: null,
        async arrayBuffer() {
          return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
        },
      };
    },
    async createImageBitmapProvider(blob) {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const source = bitmaps.get(bytes[8]);
      return { ...source, close() {} };
    },
    OffscreenCanvasProvider: class {
      constructor(width, height) {
        this.width = width;
        this.height = height;
      }

      getContext() {
        let bitmap;
        return {
          drawImage(value) { bitmap = value; },
          getImageData: () => ({ data: new Uint8ClampedArray(bitmap.data) }),
        };
      }
    },
  };

  const input = await loadSolverInput({
    mode: "screenshot",
    normalDataUrl: "https://example.test/normal.png",
    hiddenDataUrl: "https://example.test/hidden.png",
    backgroundRect: { x: 0, y: 0, width: 4, height: 4 },
    puzzleRect: { x: 1, y: 1, width: 2, height: 2 },
    viewport: { width: 4, height: 4 },
  }, providers);

  assert.equal(input.captureMode, "screenshot");
  assert.deepEqual(
    { width: input.background.width, height: input.background.height },
    { width: 4, height: 4 },
  );
  assert.deepEqual(
    { width: input.puzzle.width, height: input.puzzle.height },
    { width: 2, height: 2 },
  );
  assert.deepEqual([...input.puzzle.data.subarray(0, 4)], [90, 70, 50, 255]);
});

test("RGBA crop and difference helpers preserve exact pixel bounds", () => {
  const source = rgba(3, 2, 20);
  source.data.set([1, 2, 3, 255], (1 * 3 + 1) * 4);
  const crop = cropRgba(source, { x: 1, y: 1, width: 1, height: 1 });
  assert.deepEqual([...crop.data], [1, 2, 3, 255]);
  const delta = differenceRgba(crop, rgba(1, 1, 1));
  assert.deepEqual([...delta.data], [0, 0, 0, 0]);
});
