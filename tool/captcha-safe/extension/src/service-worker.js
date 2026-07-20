import { runCnseApiRecognition } from "./cnse-api-recognizer.js";
import {
  assertPopupSender,
  createLocalMessage,
  validateLocalMessage,
} from "./local-protocol.js";
import { createSingleFlight } from "./run-coordinator.js";

const runSingleFlight = createSingleFlight(
  (keyword) => runCnseApiRecognition(chrome, keyword),
  (keyword) => keyword,
);

function publicCode(error) {
  return typeof error?.code === "string" && /^[A-Z_]{2,64}$/u.test(error.code)
    ? error.code
    : "SOLVE_FAILED";
}

function publicMessage(error) {
  const message = typeof error?.message === "string" ? error.message : "solve failed";
  return message.replace(/[\u0000-\u001f\u007f]/gu, " ").slice(0, 256) || "solve failed";
}

function responseFor(request, type, payload) {
  return createLocalMessage({ type, requestId: request.request_id, payload });
}

async function dispatch(request) {
  if (request.type !== "solve.start") {
    throw Object.assign(new Error("unsupported request type"), { code: "MESSAGE_INVALID" });
  }
  const result = await runSingleFlight(request.payload.keyword);
  return responseFor(request, "solve.result", result);
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request?.target === "opencv-offscreen" || String(request?.type || "").startsWith("opencv.")) {
    return false;
  }
  void Promise.resolve()
    .then(() => validateLocalMessage(request))
    .then(() => {
      assertPopupSender(sender, chrome.runtime.id);
      return dispatch(request);
    })
    .then(sendResponse)
    .catch((error) => {
      try {
        sendResponse(responseFor(request, "response.error", {
          code: publicCode(error),
          message: publicMessage(error),
        }));
      } catch {}
    });

  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  console.info("Captcha Safe CNSE site helper installed");
});
