import assert from "node:assert/strict";
import test from "node:test";

import {
  detectPageChallenge,
  setDetectedPieceVisibility,
} from "../src/challenge-detector.js";

class FakeStyle {
  constructor(initial = {}) {
    this.values = new Map();
    this.priorities = new Map();
    for (const [name, value] of Object.entries(initial)) this.setProperty(name, value, "");
  }

  getPropertyValue(name) {
    return this.values.get(name) || "";
  }

  getPropertyPriority(name) {
    return this.priorities.get(name) || "";
  }

  setProperty(name, value, priority = "") {
    this.values.set(name, String(value));
    this.priorities.set(name, String(priority));
  }

  removeProperty(name) {
    const previous = this.getPropertyValue(name);
    this.values.delete(name);
    this.priorities.delete(name);
    return previous;
  }
}

class FakeRoot {
  constructor(host = null) {
    this.host = host;
    this.children = [];
  }

  append(element) {
    this.children.push(element);
    element.parentElement = null;
    element.root = this;
    return element;
  }
}

class FakeElement {
  constructor(tagName, {
    id = "",
    className = "",
    rect = { left: 0, top: 0, width: 1, height: 1 },
    attributes = {},
    computed = {},
    textContent = "",
    currentSrc = "",
    src = "",
    naturalWidth = 0,
    naturalHeight = 0,
    width = 0,
    height = 0,
    draggable = false,
    offsetLeft = undefined,
    offsetParent = null,
    inlineStyle = {},
  } = {}) {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.className = className;
    this.rect = { ...rect };
    this.attributes = new Map(Object.entries(attributes));
    this.computed = { ...computed };
    this.textContent = textContent;
    this.currentSrc = currentSrc;
    this.src = src;
    this.naturalWidth = naturalWidth;
    this.naturalHeight = naturalHeight;
    this.width = width;
    this.height = height;
    this.draggable = draggable;
    this.offsetLeft = offsetLeft;
    this.offsetParent = offsetParent;
    this.children = [];
    this.parentElement = null;
    this.root = null;
    this.shadowRoot = null;
    this.style = new FakeStyle(inlineStyle);
  }

  append(element) {
    this.children.push(element);
    element.parentElement = this;
    element.root = null;
    return element;
  }

  attachOpenShadow() {
    this.shadowRoot = new FakeRoot(this);
    return this.shadowRoot;
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  getBoundingClientRect() {
    const { left, top, width, height } = this.rect;
    return { left, top, width, height, right: left + width, bottom: top + height };
  }

  getRootNode() {
    if (this.parentElement) return this.parentElement.getRootNode();
    return this.root || this;
  }
}

function computedStyle(element) {
  const inlineVisibility = element.style.getPropertyValue("visibility");
  return {
    display: element.computed.display || "block",
    visibility: inlineVisibility || element.computed.visibility || "visible",
    opacity: element.computed.opacity ?? "1",
    cursor: element.computed.cursor || "auto",
    backgroundImage: element.computed.backgroundImage || "none",
  };
}

function appendPageSkeleton(documentObject) {
  const html = documentObject.append(new FakeElement("html", {
    rect: { left: 0, top: 0, width: 900, height: 800 },
  }));
  const body = html.append(new FakeElement("body", {
    rect: { left: 0, top: 0, width: 900, height: 800 },
  }));
  return body;
}

function addChallenge(parent, { top = 40, left = 100, css = false } = {}) {
  const panel = parent.append(new FakeElement("section", {
    className: "human-check challenge-shell",
    rect: { left: left - 20, top: top - 20, width: 340, height: 250 },
  }));
  const background = panel.append(new FakeElement(css ? "div" : "img", {
    className: "puzzle-background",
    rect: { left, top, width: 300, height: 150 },
    computed: css ? { backgroundImage: 'url("https://assets.example/bg.webp")' } : {},
    currentSrc: css ? "" : "https://assets.example/bg.png",
    naturalWidth: css ? 0 : 600,
    naturalHeight: css ? 0 : 300,
  }));
  const piece = panel.append(new FakeElement(css ? "canvas" : "img", {
    className: "jigsaw-piece",
    rect: { left: left + 5, top: top + 35, width: 50, height: 50 },
    currentSrc: css ? "" : "data:image/png;base64,cGllY2U=",
    naturalWidth: css ? 0 : 100,
    naturalHeight: css ? 0 : 100,
    width: css ? 100 : 0,
    height: css ? 100 : 0,
  }));
  const track = panel.append(new FakeElement("div", {
    className: "verification drag-track",
    rect: { left, top: top + 165, width: 300, height: 44 },
  }));
  const handle = track.append(new FakeElement("button", {
    className: "drag-handle",
    attributes: { role: "slider", "aria-label": "drag to verify" },
    rect: { left: left + 3, top: top + 167, width: 40, height: 40 },
    computed: { cursor: "grab" },
  }));
  return { panel, background, piece, track, handle };
}

function addLawyeeLikeCanvasChallenge(parent, { top = 40, left = 100 } = {}) {
  const panel = parent.append(new FakeElement("section", {
    id: "captcha",
    className: "human-check challenge-shell",
    rect: { left: left - 10, top: top - 10, width: 330, height: 230 },
  }));
  const background = panel.append(new FakeElement("canvas", {
    className: "captcha-background",
    rect: { left, top, width: 310, height: 155 },
    width: 310,
    height: 155,
  }));
  const piece = panel.append(new FakeElement("canvas", {
    className: "block",
    rect: { left, top, width: 63, height: 155 },
    width: 63,
    height: 155,
  }));
  const refresh = panel.append(new FakeElement("div", {
    className: "refreshIcon",
    rect: { left: left + 276, top, width: 34, height: 34 },
    computed: {
      cursor: "pointer",
      backgroundImage: 'url("https://assets.example/icon-sprite.png")',
    },
  }));
  const track = panel.append(new FakeElement("div", {
    className: "sliderContainer verification drag-track",
    rect: { left, top: top + 170, width: 310, height: 40 },
  }));
  const handle = track.append(new FakeElement("div", {
    className: "slider drag-handle",
    attributes: { role: "slider", "aria-label": "drag to verify" },
    rect: { left, top: top + 170, width: 40, height: 40 },
    computed: { cursor: "pointer" },
  }));
  return { panel, background, piece, refresh, track, handle };
}

function addAnonymousTallCanvasChallenge(parent, { top = 40, left = 100 } = {}) {
  const panel = parent.append(new FakeElement("section", {
    className: "widget-shell",
    rect: { left: left - 10, top: top - 10, width: 740, height: 510 },
  }));
  const background = panel.append(new FakeElement("canvas", {
    className: "captcha-background",
    rect: { left, top, width: 720, height: 360 },
    width: 720,
    height: 360,
  }));
  const piece = panel.append(new FakeElement("canvas", {
    className: "render-layer",
    rect: { left, top, width: 111, height: 360 },
    width: 111,
    height: 360,
  }));
  const refresh = panel.append(new FakeElement("div", {
    className: "refreshIcon",
    rect: { left: left + 674, top: top + 314, width: 36, height: 36 },
    computed: {
      cursor: "pointer",
      backgroundImage: 'url("https://assets.example/icon-sprite.png")',
    },
  }));
  const track = panel.append(new FakeElement("div", {
    className: "verification drag-track",
    rect: { left, top: top + 390, width: 720, height: 100 },
  }));
  const handle = track.append(new FakeElement("div", {
    className: "drag-handle",
    attributes: { role: "slider", "aria-label": "drag to verify" },
    rect: { left, top: top + 390, width: 100, height: 100 },
    computed: { cursor: "grab" },
  }));
  return { panel, background, piece, refresh, track, handle };
}

function addAnonymousFullHeightCanvasChallenge(parent, { top = 40, left = 100 } = {}) {
  const panel = parent.append(new FakeElement("section", {
    className: "vue-puzzle-vcode widget-shell",
    rect: { left: left - 10, top: top - 10, width: 380, height: 260 },
  }));
  const body = panel.append(new FakeElement("div", {
    className: "auth-body_",
    rect: { left, top, width: 360, height: 180 },
  }));
  const background = body.append(new FakeElement("canvas", {
    className: "auth-canvas1_",
    rect: { left, top, width: 360, height: 180 },
    width: 360,
    height: 180,
  }));
  const piece = body.append(new FakeElement("canvas", {
    className: "auth-canvas2_",
    rect: { left, top, width: 59, height: 180 },
    width: 59,
    height: 180,
  }));
  const refresh = body.append(new FakeElement("img", {
    className: "reset_",
    rect: { left: left + 323, top: top + 2, width: 35, height: 35 },
    currentSrc: "data:image/png;base64,cmVzZXQ=",
    naturalWidth: 40,
    naturalHeight: 40,
    computed: { cursor: "pointer" },
  }));
  const controls = panel.append(new FakeElement("div", {
    className: "auth-control_",
    rect: { left, top: top + 200, width: 360, height: 50 },
  }));
  const track = controls.append(new FakeElement("div", {
    className: "range-box",
    rect: { left, top: top + 200, width: 360, height: 50 },
  }));
  const progress = track.append(new FakeElement("div", {
    className: "range-slider",
    rect: { left, top: top + 200, width: 50, height: 50 },
  }));
  const handle = progress.append(new FakeElement("div", {
    className: "range-btn",
    rect: { left, top: top + 200, width: 50, height: 50 },
    computed: { cursor: "pointer" },
  }));
  return { panel, background, piece, refresh, track, handle };
}

function addKgCaptchaImageChallenge(parent, { top = 40, left = 100 } = {}) {
  const panel = parent.append(new FakeElement("section", {
    id: "KgCaptchaBox",
    rect: { left: left - 10, top: top - 10, width: 380, height: 245 },
  }));
  const background = panel.append(new FakeElement("div", {
    id: "KgBasemap",
    rect: { left, top, width: 360, height: 180 },
    computed: {
      backgroundImage: 'url("data:image/png;base64,YmFja2dyb3VuZA==")',
    },
  }));
  const piece = background.append(new FakeElement("img", {
    rect: { left, top, width: 72, height: 180 },
    currentSrc: "data:image/png;base64,cHV6emxlLXNoYXBl",
    naturalWidth: 72,
    naturalHeight: 180,
  }));
  piece.offsetLeft = 0;
  piece.offsetParent = background;
  const refresh = background.append(new FakeElement("img", {
    rect: { left: left + 330, top: top + 150, width: 24, height: 24 },
    currentSrc: "https://cdn.example/captcha/images/refresh.png",
    naturalWidth: 60,
    naturalHeight: 60,
    computed: { cursor: "pointer" },
  }));
  const track = panel.append(new FakeElement("div", {
    id: "KgSlide",
    rect: { left, top: top + 195, width: 360, height: 45 },
  }));
  track.append(new FakeElement("div", {
    rect: { left, top: top + 195, width: 360, height: 45 },
  }));
  track.append(new FakeElement("div", {
    rect: { left, top: top + 195, width: 360, height: 45 },
  }));
  const handle = track.append(new FakeElement("div", {
    attributes: { role: "slider", "aria-label": "drag to verify" },
    rect: { left, top: top + 196, width: 50, height: 43 },
    computed: { cursor: "pointer" },
  }));
  handle.offsetLeft = -1;
  handle.offsetParent = track;
  return { panel, background, piece, refresh, track, handle };
}

function addCnseImageChallenge(parent, { top = 40, left = 100 } = {}) {
  const panel = parent.append(new FakeElement("div", {
    id: "imgscode",
    className: "code-k-div",
    rect: { left: left - 10, top: top - 10, width: 520, height: 390 },
  }));
  const imageBox = panel.append(new FakeElement("div", {
    className: "code-img-con",
    rect: { left, top, width: 500, height: 300 },
  }));
  const background = imageBox.append(new FakeElement("img", {
    className: "code-back-img",
    rect: { left, top, width: 500, height: 300 },
    currentSrc: "data:image/png;base64,Y25zZS1iYWNrZ3JvdW5k",
    naturalWidth: 500,
    naturalHeight: 300,
  }));
  const mask = imageBox.append(new FakeElement("div", {
    className: "code-mask",
    rect: { left, top: top + 129, width: 50, height: 50 },
  }));
  const piece = mask.append(new FakeElement("img", {
    className: "code-front-img",
    rect: { left, top: top + 129, width: 50, height: 50 },
    currentSrc: "data:image/png;base64,Y25zZS1waWVjZQ==",
    naturalWidth: 50,
    naturalHeight: 50,
  }));
  const track = panel.append(new FakeElement("div", {
    className: "code-btn",
    rect: { left, top: top + 320, width: 500, height: 30 },
  }));
  const handle = track.append(new FakeElement("div", {
    className: "code-btn-img code-btn-m",
    rect: { left: left + 10, top: top + 312, width: 40, height: 40 },
    computed: { cursor: "pointer" },
  }));
  return { panel, background, piece, track, handle };
}

async function withPage(documentObject, operation) {
  const names = [
    "document",
    "getComputedStyle",
    "innerWidth",
    "innerHeight",
    "devicePixelRatio",
    "scrollX",
    "scrollY",
  ];
  const previous = new Map(names.map((name) => [name,
    Object.getOwnPropertyDescriptor(globalThis, name)]));
  Object.defineProperties(globalThis, {
    document: { configurable: true, value: documentObject },
    getComputedStyle: { configurable: true, value: computedStyle },
    innerWidth: { configurable: true, value: 900 },
    innerHeight: { configurable: true, value: 800 },
    devicePixelRatio: { configurable: true, value: 2 },
    scrollX: { configurable: true, value: 12 },
    scrollY: { configurable: true, value: 34 },
  });
  try {
    return await operation();
  } finally {
    for (const name of names) {
      const descriptor = previous.get(name);
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
}

test("detectPageChallenge returns a serializable stable descriptor for a generic image challenge", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  const challenge = addChallenge(body);

  await withPage(documentObject, () => {
    const first = detectPageChallenge();
    const second = detectPageChallenge();

    assert.equal(first.ok, true);
    assert.deepEqual(first, second);
    assert.doesNotThrow(() => JSON.stringify(first));
    assert.deepEqual(first.descriptor.handle.rect,
      { left: 103, top: 207, width: 40, height: 40 });
    assert.deepEqual(first.descriptor.track.rect,
      { left: 100, top: 205, width: 300, height: 44 });
    assert.deepEqual(first.descriptor.background.rect,
      { left: 100, top: 40, width: 300, height: 150 });
    assert.deepEqual(first.descriptor.piece.rect,
      { left: 105, top: 75, width: 50, height: 50 });
    assert.deepEqual(first.descriptor.background.resource, {
      kind: "img",
      url: "https://assets.example/bg.png",
      naturalWidth: 600,
      naturalHeight: 300,
    });
    assert.deepEqual(first.descriptor.piece.resource, {
      kind: "img",
      url: "data:image/png;base64,cGllY2U=",
      naturalWidth: 100,
      naturalHeight: 100,
    });
    assert.deepEqual(first.descriptor.viewport, {
      width: 900,
      height: 800,
      devicePixelRatio: 2,
      scrollX: 12,
      scrollY: 34,
    });
    assert.match(first.descriptor.fingerprint, /^challenge-v1-[0-9a-f]{8}$/u);
    assert.notStrictEqual(first.descriptor.piece, challenge.piece);
  });
});

test("detector recognizes the CNSE jquery.ext.slider DOM contract", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  const challenge = addCnseImageChallenge(body);

  await withPage(documentObject, () => {
    const result = detectPageChallenge();
    assert.equal(result.ok, true);
    assert.deepEqual(result.descriptor.handle.rect, challenge.handle.rect);
    assert.deepEqual(result.descriptor.track.rect, challenge.track.rect);
    assert.deepEqual(result.descriptor.background.rect, challenge.background.rect);
    assert.deepEqual(result.descriptor.piece.rect, challenge.piece.rect);
    assert.equal(result.descriptor.background.semantic.includes("code-back-img"), true);
    assert.equal(result.descriptor.piece.semantic.includes("code-front-img"), true);
  });
});

test("serialized detector scans open shadow DOM and its locator hides then exactly restores the piece", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  const host = body.append(new FakeElement("div", {
    className: "security-widget",
    rect: { left: 60, top: 10, width: 380, height: 300 },
  }));
  const shadowRoot = host.attachOpenShadow();
  const challenge = addChallenge(shadowRoot, { css: true });
  challenge.piece.style.setProperty("visibility", "visible", "");

  await withPage(documentObject, () => {
    const serializedDetector = Function(`"use strict"; return (${detectPageChallenge.toString()});`)();
    const serializedVisibility = Function(
      `"use strict"; return (${setDetectedPieceVisibility.toString()});`,
    )();
    const result = serializedDetector();

    assert.equal(result.ok, true);
    assert.equal(result.descriptor.background.resource.kind, "css");
    assert.equal(result.descriptor.background.resource.url, "https://assets.example/bg.webp");
    assert.equal(result.descriptor.piece.resource.kind, "canvas");
    assert.equal(result.descriptor.piece.resource.naturalWidth, 100);
    assert.equal(result.descriptor.piece.locator.path.includes("shadow"), true);

    const hidden = serializedVisibility(result.descriptor.piece.locator, false);
    assert.equal(hidden.ok, true);
    assert.equal(challenge.piece.style.getPropertyValue("visibility"), "hidden");
    assert.equal(challenge.piece.style.getPropertyPriority("visibility"), "important");

    const restored = serializedVisibility(result.descriptor.piece.locator, true);
    assert.equal(restored.ok, true);
    assert.equal(challenge.piece.style.getPropertyValue("visibility"), "visible");
    assert.equal(challenge.piece.style.getPropertyPriority("visibility"), "");
  });
});

test("detector selects a narrow full-height block canvas instead of a refresh control", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  const challenge = addLawyeeLikeCanvasChallenge(body);

  await withPage(documentObject, () => {
    const result = detectPageChallenge();

    assert.equal(result.ok, true);
    assert.deepEqual(result.descriptor.background.rect,
      { left: 100, top: 40, width: 310, height: 155 });
    assert.deepEqual(result.descriptor.piece.rect,
      { left: 100, top: 40, width: 63, height: 155 });
    assert.deepEqual(result.descriptor.piece.resource, {
      kind: "canvas",
      url: null,
      naturalWidth: 63,
      naturalHeight: 155,
    });
    assert.notDeepEqual(result.descriptor.piece.rect, challenge.refresh.rect);
    assert.notStrictEqual(result.descriptor.piece, challenge.piece);
  });
});

test("detector selects an anonymous narrow full-height canvas overlay", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  const challenge = addAnonymousTallCanvasChallenge(body);

  await withPage(documentObject, () => {
    const result = detectPageChallenge();

    assert.equal(result.ok, true);
    assert.deepEqual(result.descriptor.background.rect,
      { left: 100, top: 40, width: 720, height: 360 });
    assert.deepEqual(result.descriptor.piece.rect,
      { left: 100, top: 40, width: 111, height: 360 });
    assert.deepEqual(result.descriptor.piece.resource, {
      kind: "canvas",
      url: null,
      naturalWidth: 111,
      naturalHeight: 360,
    });
    assert.equal(result.descriptor.piece.semantic, "canvas render-layer");
    assert.notDeepEqual(result.descriptor.piece.rect, challenge.refresh.rect);
    assert.notStrictEqual(result.descriptor.piece, challenge.piece);
  });
});

test("detector accepts a source-shaped anonymous full-height canvas at CSS scale", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  const challenge = addAnonymousFullHeightCanvasChallenge(body);

  await withPage(documentObject, () => {
    const result = detectPageChallenge();

    assert.equal(result.ok, true);
    assert.deepEqual(result.descriptor.background.rect,
      { left: 100, top: 40, width: 360, height: 180 });
    assert.deepEqual(result.descriptor.piece.rect,
      { left: 100, top: 40, width: 59, height: 180 });
    assert.deepEqual(result.descriptor.handle.rect,
      { left: 100, top: 240, width: 50, height: 50 });
    assert.deepEqual(result.descriptor.track.rect,
      { left: 100, top: 240, width: 360, height: 50 });
    assert.equal(result.descriptor.piece.semantic, "canvas auth-canvas2_");
    assert.notDeepEqual(result.descriptor.piece.rect, challenge.refresh.rect);
  });
});

test("detector selects an anonymous full-height image and excludes a URL-named refresh image", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  const challenge = addKgCaptchaImageChallenge(body);

  await withPage(documentObject, () => {
    const result = detectPageChallenge();

    assert.equal(result.ok, true, JSON.stringify(result));
    assert.deepEqual(result.descriptor.background.rect,
      { left: 100, top: 40, width: 360, height: 180 });
    assert.deepEqual(result.descriptor.piece.rect,
      { left: 100, top: 40, width: 72, height: 180 });
    assert.deepEqual(result.descriptor.piece.resource, {
      kind: "img",
      url: "data:image/png;base64,cHV6emxlLXNoYXBl",
      naturalWidth: 72,
      naturalHeight: 180,
    });
    assert.deepEqual(result.descriptor.motion, {
      kind: "linked-offset-left",
      initialHandleOffsetLeft: -1,
      initialPieceOffsetLeft: 0,
    });
    assert.notDeepEqual(result.descriptor.piece.rect, challenge.refresh.rect);
    assert.notStrictEqual(result.descriptor.piece, challenge.piece);
  });
});

test("detector returns controlled ambiguity and not-found results without choosing arbitrarily", async () => {
  const ambiguousDocument = new FakeRoot();
  const ambiguousBody = appendPageSkeleton(ambiguousDocument);
  addChallenge(ambiguousBody, { top: 30, left: 80 });
  addChallenge(ambiguousBody, { top: 330, left: 80 });

  await withPage(ambiguousDocument, () => {
    assert.deepEqual(detectPageChallenge(), {
      ok: false,
      error: {
        code: "CHALLENGE_AMBIGUOUS",
        message: "multiple similar slider challenges were found",
      },
    });
  });

  const emptyDocument = new FakeRoot();
  appendPageSkeleton(emptyDocument).append(new FakeElement("button", {
    className: "ordinary-action",
    textContent: "Continue",
    rect: { left: 20, top: 20, width: 100, height: 40 },
  }));
  await withPage(emptyDocument, () => {
    assert.deepEqual(detectPageChallenge(), {
      ok: false,
      error: {
        code: "CHALLENGE_NOT_FOUND",
        message: "no supported visible slider challenge was found",
      },
    });
    assert.equal(setDetectedPieceVisibility({ version: 1, path: [999] }, false).error.code,
      "ELEMENT_NOT_FOUND");
    assert.equal(setDetectedPieceVisibility({ version: 1, path: ["closed"] }, false).error.code,
      "ELEMENT_LOCATOR_INVALID");
  });
});

test("detector bounds all traversed nodes, including invisible nodes", async () => {
  const documentObject = new FakeRoot();
  const body = appendPageSkeleton(documentObject);
  for (let index = 0; index < 6000; index += 1) {
    body.append(new FakeElement("span", {
      className: "irrelevant",
      rect: { left: -10, top: -10, width: 1, height: 1 },
      computed: { display: "none" },
    }));
  }

  await withPage(documentObject, () => {
    assert.equal(detectPageChallenge().error.code, "CHALLENGE_SCAN_LIMIT");
  });
});

test("detector implementation has no site/vendor allowlist and exported injections have no closure", () => {
  const detectorSource = detectPageChallenge.toString();
  const visibilitySource = setDetectedPieceVisibility.toString();

  assert.doesNotMatch(detectorSource, /aliyun|geetest|recaptcha|hcaptcha|turnstile/iu);
  assert.doesNotMatch(detectorSource, /location\.(?:host|hostname)|document\.domain/iu);
  assert.doesNotThrow(() => Function(`"use strict"; return (${detectorSource});`)());
  assert.doesNotThrow(() => Function(`"use strict"; return (${visibilitySource});`)());
});
