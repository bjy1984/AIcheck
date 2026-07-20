(function () {
  "use strict";

  const SDK_URL =
    "https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js";
  const SDK_SETTLE_DELAY_MS = 2000;
  const MAX_CLIENT_TOKEN_LENGTH = 64000;
  const STATE_VERSION = 1;
  const ALLOWED_QUERY_KEYS = new Set([
    "attemptId",
    "language",
    "prefix",
    "region",
    "sceneId",
    "userCertifyId",
  ]);
  const DEFAULT_CONFIG = Object.freeze({
    language: "cn",
    region: "cn",
  });
  const ATTEMPT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$/;
  const PREFIX_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{3,31}$/;
  const SCENE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$/;

  let clientToken = null;
  let captchaInstance = null;
  let config = null;
  let configError = null;

  try {
    config = readConfig(window.location.search);
  } catch (error) {
    configError = error;
  }

  const attemptId = config ? config.attemptId : "invalid-config";
  const internalState = {
    attemptId: attemptId,
    error: null,
    status: "INIT",
    updatedAt: new Date().toISOString(),
    version: STATE_VERSION,
  };

  const bridge = Object.freeze({
    consumeClientToken: consumeClientToken,
    getState: getState,
  });

  Object.defineProperty(window, "__captchaHarness", {
    configurable: false,
    enumerable: false,
    value: bridge,
    writable: false,
  });
  Object.defineProperty(window, "__captchaHarnessState", {
    configurable: false,
    enumerable: false,
    get: getState,
  });

  if (configError) {
    setStatus("ERROR", {
      code: safeErrorCode(configError, "INVALID_QUERY_CONFIG"),
      source: "config",
    });
    onDomReady(function () {
      renderStatus("配置无效，验证码未启动。", true);
    });
    return;
  }

  window.AliyunCaptchaConfig = Object.freeze({
    prefix: config.prefix,
    region: config.region,
  });

  onDomReady(startHarness);

  function readConfig(search) {
    const params = new URLSearchParams(search);
    const seen = new Set();

    for (const key of params.keys()) {
      if (!ALLOWED_QUERY_KEYS.has(key)) {
        throw configException("UNKNOWN_QUERY_PARAMETER");
      }
      if (seen.has(key)) {
        throw configException("DUPLICATE_QUERY_PARAMETER");
      }
      seen.add(key);
    }

    for (const key of ["attemptId", "prefix", "sceneId", "userCertifyId"]) {
      if (!params.has(key) || params.get(key) === "") {
        throw configException("MISSING_" + key.replace(/([A-Z])/g, "_$1").toUpperCase());
      }
    }

    const candidate = {
      attemptId: params.get("attemptId"),
      language: params.has("language")
        ? params.get("language")
        : DEFAULT_CONFIG.language,
      prefix: params.get("prefix"),
      region: params.has("region") ? params.get("region") : DEFAULT_CONFIG.region,
      sceneId: params.get("sceneId"),
      userCertifyId: params.get("userCertifyId"),
    };

    if (!ATTEMPT_ID_PATTERN.test(candidate.attemptId)) {
      throw configException("INVALID_ATTEMPT_ID");
    }
    if (!PREFIX_PATTERN.test(candidate.prefix)) {
      throw configException("INVALID_PREFIX");
    }
    if (!SCENE_ID_PATTERN.test(candidate.sceneId)) {
      throw configException("INVALID_SCENE_ID");
    }
    if (
      !candidate.userCertifyId.startsWith(candidate.prefix + "_") ||
      !/^[A-Za-z0-9]{10}$/.test(
        candidate.userCertifyId.slice(candidate.prefix.length + 1)
      )
    ) {
      throw configException("INVALID_USER_CERTIFY_ID");
    }
    if (candidate.region !== "cn" && candidate.region !== "sgp") {
      throw configException("INVALID_REGION");
    }
    if (candidate.language !== "cn" && candidate.language !== "en") {
      throw configException("INVALID_LANGUAGE");
    }

    return Object.freeze(candidate);
  }

  function configException(code) {
    const error = new Error(code);
    error.code = code;
    return error;
  }

  function getState() {
    const error = internalState.error
      ? Object.freeze({
          code: internalState.error.code,
          source: internalState.error.source,
        })
      : null;

    return Object.freeze({
      attemptId: internalState.attemptId,
      error: error,
      status: internalState.status,
      updatedAt: internalState.updatedAt,
      version: internalState.version,
    });
  }

  function consumeClientToken(requestedAttemptId) {
    if (
      typeof requestedAttemptId !== "string" ||
      requestedAttemptId !== internalState.attemptId ||
      clientToken === null
    ) {
      return null;
    }

    const token = clientToken;
    clientToken = null;
    internalState.updatedAt = new Date().toISOString();
    return token;
  }

  function setStatus(status, error) {
    internalState.status = status;
    internalState.error = error
      ? Object.freeze({
          code: sanitizeCode(error.code),
          source: sanitizeCode(error.source),
        })
      : null;
    internalState.updatedAt = new Date().toISOString();
  }

  function sanitizeCode(value) {
    const text = typeof value === "string" || typeof value === "number"
      ? String(value)
      : "UNSPECIFIED";
    const sanitized = text.replace(/[^A-Za-z0-9_.:-]/g, "_").slice(0, 64);
    return sanitized || "UNSPECIFIED";
  }

  function safeErrorCode(error, fallback) {
    if (error && (typeof error.code === "string" || typeof error.code === "number")) {
      return error.code;
    }
    return fallback;
  }

  function onDomReady(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback, { once: true });
      return;
    }
    callback();
  }

  function startHarness() {
    const button = document.getElementById("button");
    const placeholder = document.getElementById("captcha-element");

    if (!button || !placeholder) {
      setStatus("ERROR", { code: "MISSING_REQUIRED_ELEMENT", source: "harness" });
      renderStatus("页面结构无效，验证码未启动。", true);
      return;
    }

    button.disabled = true;
    button.addEventListener("click", handleTrigger, true);
    loadSdk();
  }

  function loadSdk() {
    const sdkScript = document.createElement("script");
    sdkScript.async = true;
    sdkScript.referrerPolicy = "no-referrer";
    sdkScript.src = SDK_URL;
    sdkScript.addEventListener("load", initializeCaptcha, { once: true });
    sdkScript.addEventListener(
      "error",
      function () {
        setStatus("ERROR", { code: "SDK_LOAD_FAILED", source: "sdk" });
        disableButton();
        renderStatus("验证码组件加载失败。", true);
      },
      { once: true }
    );
    document.head.appendChild(sdkScript);
  }

  function initializeCaptcha() {
    if (typeof window.initAliyunCaptcha !== "function") {
      setStatus("ERROR", { code: "SDK_INIT_UNAVAILABLE", source: "sdk" });
      disableButton();
      renderStatus("验证码组件初始化失败。", true);
      return;
    }

    const initializedAt = Date.now();

    try {
      window.initAliyunCaptcha({
        SceneId: config.sceneId,
        UserCertifyId: config.userCertifyId,
        button: "#button",
        element: "#captcha-element",
        fail: handleFailure,
        getInstance: function (instance) {
          captchaInstance = instance;
          const remainingDelay = Math.max(
            0,
            SDK_SETTLE_DELAY_MS - (Date.now() - initializedAt)
          );
          window.setTimeout(markReady, remainingDelay);
        },
        language: config.language,
        mode: "popup",
        onClose: handleClose,
        onError: handleSdkError,
        slideStyle: {
          height: 40,
          width: 360,
        },
        success: handleSuccess,
      });
    } catch (error) {
      setStatus("ERROR", {
        code: safeErrorCode(error, "SDK_INIT_EXCEPTION"),
        source: "sdk",
      });
      disableButton();
      renderStatus("验证码组件初始化失败。", true);
    }
  }

  function markReady() {
    if (!captchaInstance || internalState.status !== "INIT") {
      return;
    }
    setStatus("READY", null);
    const button = document.getElementById("button");
    if (button) {
      button.disabled = false;
    }
    renderStatus("验证码已就绪。", false);
  }

  function handleTrigger(event) {
    if (!event.isTrusted || internalState.status !== "READY") {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }

    clientToken = null;
    setStatus("CHALLENGE_OPEN", null);
    renderStatus("请在弹窗中完成验证。", false);
  }

  function handleSuccess(captchaVerifyParam) {
    if (
      internalState.status !== "CHALLENGE_OPEN" &&
      internalState.status !== "CLIENT_FAIL"
    ) {
      clientToken = null;
      setStatus("ERROR", {
        code: "UNEXPECTED_SUCCESS_CALLBACK",
        source: "callback",
      });
      disableButton();
      renderStatus("验证码返回顺序异常。", true);
      return;
    }

    if (
      typeof captchaVerifyParam !== "string" ||
      captchaVerifyParam.length === 0 ||
      captchaVerifyParam.length > MAX_CLIENT_TOKEN_LENGTH
    ) {
      clientToken = null;
      setStatus("ERROR", { code: "INVALID_CLIENT_TOKEN", source: "callback" });
      disableButton();
      renderStatus("验证码返回了无效结果。", true);
      return;
    }

    clientToken = captchaVerifyParam;
    setStatus("CLIENT_PASS", null);
    disableButton();
    renderStatus("客户端验证已完成，等待服务端校验。", false);
  }

  function handleFailure(result) {
    if (
      internalState.status !== "CHALLENGE_OPEN" &&
      internalState.status !== "CLIENT_FAIL"
    ) {
      clientToken = null;
      setStatus("ERROR", {
        code: "UNEXPECTED_FAILURE_CALLBACK",
        source: "callback",
      });
      disableButton();
      renderStatus("验证码返回顺序异常。", true);
      return;
    }

    clientToken = null;
    setStatus("CLIENT_FAIL", {
      code: safeErrorCode(result, "CAPTCHA_REJECTED"),
      source: "callback",
    });
    renderStatus("客户端验证未通过，请重试。", true);
  }

  function handleSdkError(errorInfo) {
    clientToken = null;
    setStatus("ERROR", {
      code: safeErrorCode(errorInfo, "SDK_RUNTIME_ERROR"),
      source: "sdk",
    });
    disableButton();
    renderStatus("验证码组件发生错误。", true);
  }

  function handleClose(reason) {
    if (
      reason === "userDismiss" &&
      (internalState.status === "CHALLENGE_OPEN" ||
        internalState.status === "CLIENT_FAIL")
    ) {
      setStatus("READY", null);
      const button = document.getElementById("button");
      if (button) {
        button.disabled = false;
      }
      renderStatus("验证码已就绪。", false);
    }
  }

  function disableButton() {
    const button = document.getElementById("button");
    if (button) {
      button.disabled = true;
    }
  }

  function renderStatus(message, isError) {
    const status = document.getElementById("harness-status");
    if (!status) {
      return;
    }
    status.textContent = message;
    status.classList.toggle("status-error", Boolean(isError));
  }
})();
