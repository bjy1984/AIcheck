import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateCnseMoveLength,
  fetchCnseChallenge,
  runCnseApiRecognition,
  submitCnseOrgSearch,
} from "../src/cnse-api-recognizer.js";

const API_RESULT = {
  ok: true,
  endpoint: "/info-pub/pub/orgSearchVCodeData.json",
  keyword: "新疆智仁能源有限公司拜城县察尔齐加气站",
  yHeight: 51,
  backgroundDataUrl: "data:image/png;base64,Ymln",
  puzzleDataUrl: "data:image/png;base64,c21hbGw=",
};

const SOLVED = {
  algorithm: "opencv-edge-template-v1",
  captureMode: "resource",
  confidence: 0.91,
  background: { width: 500, height: 281 },
  puzzle: { width: 55, height: 45 },
  matchBox: { x: 178, y: 51, width: 55, height: 45 },
  targetCenter: { x: 205, y: 73 },
};

const ROW = {
  dwid: "46c6accf-684e-4d0c-bb49-a42f72fa9f1f",
  fzjg: "新疆维吾尔自治区阿克苏地区市场监督管理局",
  zsyxq: "2029-01-25",
  dwmc: "新疆智仁能源有限公司拜城县察尔齐加气站",
  dwlb: "特种设备气体充装单位",
  sjgxsj: "2026-07-20",
  zsyxqyz: "",
};

test("CNSE moveLength uses the API image x coordinate minus one without page geometry", () => {
  assert.equal(calculateCnseMoveLength(API_RESULT, SOLVED), 177);
});

test("page injection fetches only the CNSE GET envelope and returns bounded image data", async () => {
  const names = ["location", "fetch"];
  const previous = new Map(names.map((name) => [name,
    Object.getOwnPropertyDescriptor(globalThis, name)]));
  const requested = [];
  Object.defineProperties(globalThis, {
    location: {
      configurable: true,
      value: { origin: "https://cnse.e-cqs.cn", pathname: "/info-pub/pub" },
    },
    fetch: {
      configurable: true,
      value: async (url, options) => {
        requested.push({ url, options });
        return {
          ok: true,
          async json() {
            return {
              errcode: 0,
              errmsg: "success",
              yHeight: 51,
              smallImage: "c21hbGxJbWFnZQ==",
              bigImage: "YmlnSW1hZ2VEYXRh",
            };
          },
        };
      },
    },
  });
  try {
    const result = await fetchCnseChallenge(API_RESULT.keyword);
    assert.equal(result.ok, true);
    assert.equal(result.yHeight, 51);
    assert.equal(result.backgroundDataUrl, "data:image/png;base64,YmlnSW1hZ2VEYXRh");
    assert.equal(result.puzzleDataUrl, "data:image/png;base64,c21hbGxJbWFnZQ==");
    assert.equal(result.keyword, API_RESULT.keyword);
    assert.equal(requested.length, 1);
    assert.equal(requested[0].url, "/info-pub/pub/orgSearchVCodeData.json");
    assert.equal(requested[0].options.method, "GET");
    assert.equal(requested[0].options.credentials, "same-origin");
  } finally {
    for (const name of names) {
      const descriptor = previous.get(name);
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});

test("page injection submits a same-origin form POST with moveLength and returns bounded rows", async () => {
  const names = ["location", "fetch"];
  const previous = new Map(names.map((name) => [name,
    Object.getOwnPropertyDescriptor(globalThis, name)]));
  const requested = [];
  Object.defineProperties(globalThis, {
    location: {
      configurable: true,
      value: { origin: "https://cnse.e-cqs.cn", pathname: "/info-pub/pub" },
    },
    fetch: {
      configurable: true,
      value: async (url, options) => {
        requested.push({ url, options });
        return { ok: true, async json() { return { total: 1, rows: [ROW] }; } };
      },
    },
  });
  try {
    const result = await submitCnseOrgSearch(API_RESULT.keyword, 177);
    assert.deepEqual(result, {
      ok: true,
      endpoint: "/info-pub/pub/orgSearchData.json",
      keyword: API_RESULT.keyword,
      total: 1,
      rows: [ROW],
    });
    assert.equal(requested.length, 1);
    assert.equal(requested[0].url, "/info-pub/pub/orgSearchData.json");
    assert.equal(requested[0].options.method, "POST");
    assert.equal(requested[0].options.credentials, "same-origin");
    assert.deepEqual(Object.fromEntries(new URLSearchParams(requested[0].options.body)), {
      keyword: API_RESULT.keyword,
      moveLength: "177",
      pageNumber: "1",
      pageSize: "10",
    });
  } finally {
    for (const name of names) {
      const descriptor = previous.get(name);
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  }
});

test("runtime recognizes API images without debugger or pointer dispatch", async () => {
  const calls = { injected: [], messages: [], offscreenCreate: 0, offscreenClose: 0 };
  const chromeApi = {
    tabs: {
      async query() {
        return [{ id: 7, url: "https://cnse.e-cqs.cn/info-pub/pub" }];
      },
    },
    scripting: {
      async executeScript(options) {
        calls.injected.push(options);
        if (options.func === submitCnseOrgSearch) {
          return [{ frameId: 0, result: {
            ok: true,
            endpoint: "/info-pub/pub/orgSearchData.json",
            keyword: API_RESULT.keyword,
            total: 1,
            rows: [structuredClone(ROW)],
          } }];
        }
        return [{ frameId: 0, result: structuredClone(API_RESULT) }];
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
        calls.messages.push(structuredClone(message));
        return {
          type: "opencv.result",
          requestId: message.requestId,
          result: structuredClone(SOLVED),
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
  };
  const result = await runCnseApiRecognition(chromeApi, API_RESULT.keyword);
  assert.deepEqual(result, {
    status: "COMPLETED",
    algorithm: "opencv-edge-template-v1",
    captureMode: "api",
    confidence: 0.91,
    moveLength: 177,
    apiYHeight: 51,
    keyword: API_RESULT.keyword,
    queryEndpoint: "/info-pub/pub/orgSearchData.json",
    total: 1,
    rows: [ROW],
    targetCenter: { x: 205, y: 73 },
    matchBox: { x: 178, y: 51, width: 55, height: 45 },
  });
  assert.equal(calls.injected.length, 2);
  assert.equal(calls.injected[0].world, "MAIN");
  assert.equal(calls.injected[0].func, fetchCnseChallenge);
  assert.deepEqual(calls.injected[0].args, [API_RESULT.keyword]);
  assert.equal(calls.injected[1].func, submitCnseOrgSearch);
  assert.deepEqual(calls.injected[1].args, [API_RESULT.keyword, 177]);
  assert.equal(calls.messages.length, 1);
  assert.deepEqual(calls.messages[0].payload, {
    mode: "resource",
    backgroundUrl: API_RESULT.backgroundDataUrl,
    puzzleUrl: API_RESULT.puzzleDataUrl,
  });
  assert.equal(calls.offscreenCreate, 1);
  assert.equal(calls.offscreenClose, 1);
  assert.equal("debugger" in chromeApi, false);
});
