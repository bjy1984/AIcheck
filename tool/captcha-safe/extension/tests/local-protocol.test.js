import assert from "node:assert/strict";
import test from "node:test";

import {
  assertPopupSender,
  createLocalMessage,
  ProtocolError,
  randomRequestId,
  validateLocalMessage,
} from "../src/local-protocol.js";

const EXTENSION_ID = "bllipfmjmddgmgaabfmfhlkgbdhdiepe";
const REQUEST_ID = "r".repeat(24);

test("local protocol accepts only solve start/result and error envelopes", () => {
  const messages = [
    createLocalMessage({
      type: "solve.start",
      requestId: REQUEST_ID,
      payload: { keyword: "测试单位" },
    }),
    createLocalMessage({
      type: "solve.result",
      requestId: REQUEST_ID,
      payload: {
        algorithm: "opencv-edge-template-v1",
        apiYHeight: 51,
        captureMode: "api",
        confidence: 0.91,
        matchBox: { x: 178, y: 51, width: 55, height: 45 },
        moveLength: 177,
        keyword: "测试单位",
        queryEndpoint: "/info-pub/pub/orgSearchData.json",
        rows: [],
        status: "COMPLETED",
        targetCenter: { x: 201, y: 54 },
        total: 0,
      },
    }),
    createLocalMessage({
      type: "response.error",
      requestId: REQUEST_ID,
      payload: { code: "SOLVER_FAILED", message: "OpenCV solver failed" },
    }),
  ];

  for (const message of messages) {
    assert.equal(validateLocalMessage(message), message);
    assert.deepEqual(Object.keys(message).sort(), ["payload", "request_id", "type", "v"]);
  }
});

test("local protocol rejects expanded operations, payloads, envelopes, and identifiers", () => {
  const valid = createLocalMessage({
    type: "solve.start",
    requestId: REQUEST_ID,
    payload: { keyword: "测试单位" },
  });
  const cases = [
    { ...valid, extra: false },
    { ...valid, v: 2 },
    { ...valid, request_id: "short" },
    { ...valid, type: "page.inspect" },
    { ...valid, payload: { keyword: "测试单位", target: "https://example.invalid/" } },
    { ...valid, payload: null },
    { ...valid, request_id: "\u00e9".repeat(24) },
  ];
  for (const value of cases) {
    assert.throws(() => validateLocalMessage(value), ProtocolError);
  }
});

test("popup sender is bound to the exact extension popup frame", () => {
  const url = `chrome-extension://${EXTENSION_ID}/popup/popup.html`;
  assert.equal(
    assertPopupSender(
      {
        id: EXTENSION_ID,
        frameId: 0,
        origin: `chrome-extension://${EXTENSION_ID}`,
        url,
      },
      EXTENSION_ID,
    ),
    true,
  );

  for (const sender of [
    { id: EXTENSION_ID, frameId: 1, url },
    { id: "a".repeat(32), frameId: 0, url },
    { id: EXTENSION_ID, frameId: 0, url: `${url}?expanded=1` },
    { id: EXTENSION_ID, frameId: 0, url: `chrome-extension://${EXTENSION_ID}/drag-test/index.html` },
    { id: EXTENSION_ID, frameId: 0, url: "https://example.invalid/popup/popup.html" },
  ]) {
    assert.throws(() => assertPopupSender(sender, EXTENSION_ID), ProtocolError);
  }
});

test("request ID generation is fixed-length URL-safe and fails without secure randomness", () => {
  let next = 0;
  const provider = {
    getRandomValues(bytes) {
      for (let index = 0; index < bytes.length; index += 1) {
        bytes[index] = next % 256;
        next += 17;
      }
      return bytes;
    },
  };
  assert.match(randomRequestId(provider), /^[A-Za-z0-9_-]{24}$/u);
  assert.throws(() => randomRequestId({}), /secure request ID generation is unavailable/u);
});
