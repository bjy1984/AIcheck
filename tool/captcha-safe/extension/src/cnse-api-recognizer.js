import {
  settleWithin,
  solveWithOffscreen,
  SolverRunError,
} from "./solve-runner.js";

const ALLOWED_ORIGIN = "https://cnse.e-cqs.cn";
const ALLOWED_PATH_PREFIX = "/info-pub/";
const CAPTCHA_ENDPOINT = "/info-pub/pub/orgSearchVCodeData.json";
const SEARCH_ENDPOINT = "/info-pub/pub/orgSearchData.json";
const CHROME_API_TIMEOUT_MS = 25_000;

function fail(code, message) {
  throw new SolverRunError(code, message);
}

// Passed directly to chrome.scripting.executeScript in the page's MAIN world.
// Keep this function self-contained: Chrome serializes it without module scope.
export async function fetchCnseChallenge(keyword) {
  const errorResult = (code, message) => ({ ok: false, error: { code, message } });
  try {
    if (globalThis.location?.origin !== "https://cnse.e-cqs.cn" ||
        !String(globalThis.location?.pathname || "").startsWith("/info-pub/")) {
      return errorResult("SITE_NOT_SUPPORTED", "page is outside the CNSE public-search site");
    }
    const normalizedKeyword = String(keyword || "").replace(/ /gu, "").trim();
    const keywordBytes = new TextEncoder().encode(normalizedKeyword).byteLength;
    if (keywordBytes < 1 || keywordBytes > 512) {
      return errorResult("CNSE_KEYWORD_INVALID", "请输入有效的单位名称");
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20_000);
    let response;
    try {
      response = await globalThis.fetch("/info-pub/pub/orgSearchVCodeData.json", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    if (!response?.ok) {
      return errorResult("CNSE_API_FAILED", "CNSE captcha API request failed");
    }
    const data = await response.json();
    const fields = data && typeof data === "object" && !Array.isArray(data)
      ? Object.keys(data).sort() : [];
    const expectedFields = ["bigImage", "errcode", "errmsg", "smallImage", "yHeight"];
    if (fields.length !== expectedFields.length ||
        fields.some((field, index) => field !== expectedFields[index]) ||
        data.errcode !== 0 || data.errmsg !== "success" ||
        !Number.isSafeInteger(data.yHeight) || data.yHeight < 0 || data.yHeight > 4096) {
      return errorResult("CNSE_API_INVALID", "CNSE captcha API returned an invalid envelope");
    }
    const base64Image = (value) => typeof value === "string" &&
      value.length >= 16 && value.length <= 12_000_000 &&
      value.length % 4 === 0 && /^[A-Za-z0-9+/]+={0,2}$/u.test(value);
    if (!base64Image(data.smallImage) || !base64Image(data.bigImage)) {
      return errorResult("CNSE_API_INVALID", "CNSE captcha API returned invalid image data");
    }
    return {
      ok: true,
      endpoint: "/info-pub/pub/orgSearchVCodeData.json",
      keyword: normalizedKeyword,
      yHeight: data.yHeight,
      backgroundDataUrl: `data:image/png;base64,${data.bigImage}`,
      puzzleDataUrl: `data:image/png;base64,${data.smallImage}`,
    };
  } catch (error) {
    const message = error?.name === "AbortError"
      ? "CNSE captcha API request timed out"
      : "CNSE captcha API request could not be completed";
    return errorResult("CNSE_API_FAILED", message);
  }
}

// Passed directly to chrome.scripting.executeScript in the page's MAIN world.
// Cookies stay inside the same-origin page context and are never returned to the extension.
export async function submitCnseOrgSearch(keyword, moveLength) {
  const errorResult = (code, message) => ({ ok: false, error: { code, message } });
  try {
    if (globalThis.location?.origin !== "https://cnse.e-cqs.cn" ||
        !String(globalThis.location?.pathname || "").startsWith("/info-pub/")) {
      return errorResult("SITE_NOT_SUPPORTED", "page is outside the CNSE public-search site");
    }
    const normalizedKeyword = String(keyword || "").replace(/ /gu, "").trim();
    const keywordBytes = new TextEncoder().encode(normalizedKeyword).byteLength;
    if (keywordBytes < 1 || keywordBytes > 512 ||
        typeof moveLength !== "number" || !Number.isFinite(moveLength) ||
        moveLength < 0 || moveLength > 65_535) {
      return errorResult("CNSE_QUERY_INVALID", "CNSE query parameters are invalid");
    }
    const body = new URLSearchParams({
      keyword: normalizedKeyword,
      moveLength: String(moveLength),
      pageNumber: "1",
      pageSize: "10",
    });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20_000);
    let response;
    try {
      response = await globalThis.fetch("/info-pub/pub/orgSearchData.json", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: body.toString(),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    if (!response?.ok) {
      return errorResult("CNSE_QUERY_FAILED", "CNSE organization query request failed");
    }
    const data = await response.json();
    if (!data || !Number.isSafeInteger(data.total) || data.total < 0 ||
        data.total > 1_000_000 || !Array.isArray(data.rows) || data.rows.length > 10) {
      const message = typeof data?.messageText === "string"
        ? data.messageText.slice(0, 128) : "CNSE organization query returned invalid data";
      return errorResult("CNSE_QUERY_REJECTED", message);
    }
    const fields = ["dwid", "fzjg", "zsyxq", "dwmc", "dwlb", "sjgxsj", "zsyxqyz"];
    const rows = [];
    for (const row of data.rows) {
      if (!row || typeof row !== "object" || Array.isArray(row)) {
        return errorResult("CNSE_QUERY_INVALID", "CNSE organization row is invalid");
      }
      const clean = {};
      for (const field of fields) {
        if (typeof row[field] !== "string" ||
            new TextEncoder().encode(row[field]).byteLength > 1024) {
          return errorResult("CNSE_QUERY_INVALID", "CNSE organization row is invalid");
        }
        clean[field] = row[field];
      }
      rows.push(clean);
    }
    return {
      ok: true,
      endpoint: "/info-pub/pub/orgSearchData.json",
      keyword: normalizedKeyword,
      total: data.total,
      rows,
    };
  } catch (error) {
    const message = error?.name === "AbortError"
      ? "CNSE organization query timed out"
      : "CNSE organization query could not be completed";
    return errorResult("CNSE_QUERY_FAILED", message);
  }
}

function validateActiveUrl(tab) {
  if (!Number.isInteger(tab?.id) || typeof tab.url !== "string") {
    fail("ACTIVE_PAGE_NOT_FOUND", "no active web page was found");
  }
  let url;
  try {
    url = new URL(tab.url);
  } catch {
    fail("ACTIVE_PAGE_INVALID", "active tab URL is invalid");
  }
  if (url.origin !== ALLOWED_ORIGIN || !url.pathname.startsWith(ALLOWED_PATH_PREFIX)) {
    fail("SITE_NOT_SUPPORTED", "请在全国特种设备公示信息查询平台页面上使用此扩展");
  }
}

export function calculateCnseMoveLength(apiResult, solved) {
  if (!apiResult || !solved?.background || !solved?.matchBox ||
      !Number.isSafeInteger(solved.background.width) || solved.background.width <= 1 ||
      !Number.isSafeInteger(solved.matchBox.x) || solved.matchBox.x < 1 ||
      solved.matchBox.x >= solved.background.width) {
    fail("CNSE_COORDINATE_INVALID", "CNSE API recognition coordinate is invalid");
  }
  return solved.matchBox.x - 1;
}

export async function runCnseApiRecognition(chromeApi, keyword) {
  const required = [
    chromeApi?.tabs?.query,
    chromeApi?.scripting?.executeScript,
    chromeApi?.offscreen?.createDocument,
  ];
  if (required.some((value) => typeof value !== "function")) {
    fail("EXTENSION_API_UNAVAILABLE", "required Chrome extension APIs are unavailable");
  }
  const tabs = await settleWithin(
    chromeApi.tabs.query({ active: true, currentWindow: true }),
    CHROME_API_TIMEOUT_MS,
    "ACTIVE_PAGE_TIMEOUT",
    "the active page lookup did not finish in time",
  );
  const tab = tabs[0];
  validateActiveUrl(tab);
  const injected = await settleWithin(
    chromeApi.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      func: fetchCnseChallenge,
      args: [keyword],
    }),
    CHROME_API_TIMEOUT_MS,
    "CNSE_API_TIMEOUT",
    "CNSE captcha API request did not finish in time",
  );
  const apiResult = injected?.[0]?.result;
  if (apiResult?.ok !== true) {
    fail(
      typeof apiResult?.error?.code === "string" ? apiResult.error.code : "CNSE_API_FAILED",
      typeof apiResult?.error?.message === "string"
        ? apiResult.error.message : "CNSE captcha API request failed",
    );
  }
  const solved = await solveWithOffscreen(chromeApi, {
    mode: "resource",
    backgroundUrl: apiResult.backgroundDataUrl,
    puzzleUrl: apiResult.puzzleDataUrl,
  });
  if (Math.abs(solved.matchBox.y - apiResult.yHeight) > 4) {
    fail("CNSE_VERTICAL_MISMATCH", "recognized gap does not match the API yHeight");
  }
  const moveLength = calculateCnseMoveLength(apiResult, solved);
  const submitted = await settleWithin(
    chromeApi.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      func: submitCnseOrgSearch,
      args: [apiResult.keyword, moveLength],
    }),
    CHROME_API_TIMEOUT_MS,
    "CNSE_QUERY_TIMEOUT",
    "CNSE organization query did not finish in time",
  );
  const queryResult = submitted?.[0]?.result;
  if (queryResult?.ok !== true) {
    fail(
      typeof queryResult?.error?.code === "string"
        ? queryResult.error.code : "CNSE_QUERY_FAILED",
      typeof queryResult?.error?.message === "string"
        ? queryResult.error.message : "CNSE organization query failed",
    );
  }
  return Object.freeze({
    status: "COMPLETED",
    algorithm: solved.algorithm,
    captureMode: "api",
    confidence: solved.confidence,
    moveLength,
    apiYHeight: apiResult.yHeight,
    keyword: queryResult.keyword,
    queryEndpoint: SEARCH_ENDPOINT,
    total: queryResult.total,
    rows: queryResult.rows.map((row) => Object.freeze({ ...row })),
    targetCenter: Object.freeze({ ...solved.targetCenter }),
    matchBox: Object.freeze({ ...solved.matchBox }),
  });
}
