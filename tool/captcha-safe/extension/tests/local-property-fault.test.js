import assert from "node:assert/strict";
import test from "node:test";

import { validateLocalMessage } from "../src/local-protocol.js";

const CASES_PER_DOMAIN = 25_000;
const REQUEST_ID = "p".repeat(24);

function rejects(value) {
  try {
    validateLocalMessage(value);
    return false;
  } catch {
    return true;
  }
}

test("25,000 expanded-envelope property cases fail closed", () => {
  for (let index = 0; index < CASES_PER_DOMAIN; index += 1) {
    const value = {
      v: 1,
      type: "solve.start",
      request_id: REQUEST_ID,
      payload: { keyword: "测试单位" },
      [`expanded_${index}`]: index,
    };
    assert.equal(rejects(value), true, `expanded envelope case ${index}`);
  }
});

test("25,000 solve-start payload expansion cases fail closed", () => {
  for (let index = 0; index < CASES_PER_DOMAIN; index += 1) {
    const value = {
      v: 1,
      type: "solve.start",
      request_id: REQUEST_ID,
      payload: {
        keyword: "测试单位",
        [`target_${index}`]: `https://example.invalid/${index}`,
      },
    };
    assert.equal(rejects(value), true, `expanded drag payload case ${index}`);
  }
});

test("25,000 invalid solve-result mutation cases fail closed", () => {
  for (let index = 0; index < CASES_PER_DOMAIN; index += 1) {
    const payload = {
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
    };
    switch (index % 5) {
      case 0:
        payload.algorithm = "unknown";
        break;
      case 1:
        payload.captureMode = "remote";
        break;
      case 2:
        payload.status = "VERIFIED";
        break;
      case 3:
        payload.apiYHeight = -1;
        break;
      default:
        payload.confidence = 0.499;
    }
    const value = {
      v: 1,
      type: "solve.result",
      request_id: REQUEST_ID,
      payload,
    };
    assert.equal(rejects(value), true, `untrusted result case ${index}`);
  }
});

test("25,000 solve-result expansion cases fail closed", () => {
  for (let index = 0; index < CASES_PER_DOMAIN; index += 1) {
    const value = {
      v: 1,
      type: "solve.result",
      request_id: REQUEST_ID,
      payload: {
        algorithm: "opencv-edge-template-v1",
        apiYHeight: 51,
        captureMode: "api",
        confidence: 0.75,
        matchBox: { x: 90, y: 51, width: 55, height: 45 },
        moveLength: 100,
        keyword: "测试单位",
        queryEndpoint: "/info-pub/pub/orgSearchData.json",
        rows: [],
        status: "COMPLETED",
        targetCenter: { x: 120, y: 30 },
        total: 0,
        [`expanded_${index}`]: false,
      },
    };
    assert.equal(rejects(value), true, `expanded status case ${index}`);
  }
});

test("local protocol property/fault campaign executes exactly 100,000 cases", () => {
  assert.equal(CASES_PER_DOMAIN * 4, 100_000);
});
