import { loadSolverInput } from "./image-input.js";
import {
  DEFAULT_MIN_CONFIDENCE,
  OpenCvSolverError,
  solvePuzzleImages,
  waitForOpenCvRuntime,
} from "./opencv-solver.js";

const REQUEST_ID = /^[A-Za-z0-9_-]{1,128}$/u;
let active = false;

function publicError(error) {
  const code = error instanceof OpenCvSolverError && /^[A-Z_]{2,64}$/u.test(error.code)
    ? error.code
    : "OPENCV_SOLVE_FAILED";
  const rawMessage = error instanceof Error ? error.message : "OpenCV solve failed";
  const message = rawMessage
    .replace(/[\u0000-\u001f\u007f]/gu, " ")
    .slice(0, 256) || "OpenCV solve failed";
  return Object.freeze({ code, message });
}

function validateRequest(message, sender) {
  if (sender?.id !== chrome.runtime.id) {
    throw new OpenCvSolverError("MESSAGE_INVALID", "OpenCV request sender is invalid");
  }
  if (
    !message ||
    typeof message !== "object" ||
    Array.isArray(message) ||
    message.target !== "opencv-offscreen" ||
    message.type !== "opencv.solve" ||
    typeof message.requestId !== "string" ||
    !REQUEST_ID.test(message.requestId)
  ) {
    throw new OpenCvSolverError("MESSAGE_INVALID", "OpenCV request is invalid");
  }
  return message;
}

async function handleSolve(message, sender) {
  const request = validateRequest(message, sender);
  if (active) throw new OpenCvSolverError("RUN_BUSY", "an OpenCV solve is already running");
  active = true;
  try {
    const { runtime } = await waitForOpenCvRuntime(globalThis.cv);
    const input = await loadSolverInput(request.payload);
    const match = solvePuzzleImages({
      background: input.background,
      puzzle: input.puzzle,
      minConfidence: DEFAULT_MIN_CONFIDENCE,
    }, runtime);
    return Object.freeze({
      type: "opencv.result",
      requestId: request.requestId,
      result: Object.freeze({ ...match, captureMode: input.captureMode }),
    });
  } finally {
    active = false;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.target !== "opencv-offscreen" || message?.type !== "opencv.solve") return false;
  void handleSolve(message, sender)
    .then(sendResponse)
    .catch((error) => {
      sendResponse({
        type: "opencv.error",
        requestId: typeof message?.requestId === "string" ? message.requestId.slice(0, 128) : "invalid",
        error: publicError(error),
      });
    });
  return true;
});
