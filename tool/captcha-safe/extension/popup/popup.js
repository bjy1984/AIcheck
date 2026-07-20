import {
  createLocalMessage,
  randomRequestId,
  validateLocalMessage,
} from "../src/local-protocol.js";
const dragTestButton = document.getElementById("run-drag-test");
const dragTestBadge = document.getElementById("drag-test-badge");
const dragTestResult = document.getElementById("drag-test-result");
const queryData = document.getElementById("query-data");
const summary = document.getElementById("summary");
const queryKeyword = document.getElementById("query-keyword");
const metricDistance = document.getElementById("metric-distance");
const metricConfidence = document.getElementById("metric-confidence");
const metricTotal = document.getElementById("metric-total");
const resultList = document.getElementById("result-list");
const copyResultButton = document.getElementById("copy-result");
const buttonLabel = dragTestButton.querySelector(".button-label");
const keywordInput = document.getElementById("keyword");
const steps = ["step-captcha", "step-solve", "step-query"].map((id) => document.getElementById(id));
let dragTestBusy = false;
let latestJson = "";

function envelope(type, payload) {
  return createLocalMessage({
    type,
    requestId: randomRequestId(),
    payload,
  });
}

async function request(type, payload) {
  const outgoing = envelope(type, payload);
  const incoming = await chrome.runtime.sendMessage(outgoing);
  validateLocalMessage(incoming);
  if (incoming.request_id !== outgoing.request_id) {
    throw new Error("响应绑定不匹配");
  }
  if (incoming.type === "response.error") {
    const error = new Error(incoming.payload.message);
    error.code = incoming.payload.code;
    throw error;
  }
  const expectedType = { "solve.start": "solve.result" }[type];
  if (incoming.type !== expectedType) throw new Error("响应类型不匹配");
  return incoming;
}

function showPending(button, badge, result, text) {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  badge.className = "badge running";
  badge.innerHTML = '<span class="status-dot"></span>运行中';
  result.className = "inline-status";
  result.setAttribute("role", "status");
  result.textContent = text;
  buttonLabel.textContent = "正在处理…";
  steps.forEach((step, index) => { step.className = index === 0 ? "step active" : "step"; });
}

function showSuccess(button, badge, result, text) {
  button.disabled = false;
  button.removeAttribute("aria-busy");
  badge.className = "badge success";
  badge.innerHTML = '<span class="status-dot"></span>已完成';
  result.className = "inline-status success";
  result.setAttribute("role", "status");
  result.textContent = text;
  buttonLabel.textContent = "重新查询";
  steps.forEach((step) => { step.className = "step done"; });
}

function showFailure(button, badge, result, error) {
  button.disabled = false;
  button.removeAttribute("aria-busy");
  badge.className = "badge error";
  badge.innerHTML = '<span class="status-dot"></span>失败';
  result.className = "inline-status error";
  result.setAttribute("role", "alert");
  const recovery = {
    SITE_NOT_SUPPORTED: "请确认当前地址是 https://cnse.e-cqs.cn/info-pub/pub。",
    CNSE_KEYWORD_INVALID: "请在扩展中输入有效的单位名称。",
    CNSE_QUERY_REJECTED: "验证码可能已过期，请直接点击重试查询。",
  }[error.code];
  result.textContent = `${error.code || "RUN_FAILED"}：${error.message}${recovery ? ` ${recovery}` : ""}`;
  buttonLabel.textContent = "重试查询";
  const activeStep = String(error.code || "").includes("QUERY") ? 2
    : String(error.code || "").includes("OPENCV") || String(error.code || "").includes("VERTICAL") ? 1 : 0;
  steps.forEach((step, index) => { step.className = index < activeStep ? "step done" : index === activeStep ? "step error" : "step"; });
}

function renderRows(rows) {
  resultList.replaceChildren();
  if (rows.length === 0) {
    const empty = document.createElement("p");
    empty.className = "inline-status";
    empty.textContent = "查询成功，但没有匹配记录。";
    resultList.append(empty);
    return;
  }
  for (const row of rows) {
    const item = document.createElement("article");
    item.className = "result-item";
    const name = document.createElement("strong");
    name.textContent = row.dwmc;
    const meta = document.createElement("div");
    meta.className = "result-meta";
    for (const text of [row.dwlb, `有效期至 ${row.zsyxq}`, row.fzjg]) {
      const span = document.createElement("span");
      span.textContent = text;
      meta.append(span);
    }
    item.append(name, meta);
    resultList.append(item);
  }
}

copyResultButton.addEventListener("click", async () => {
  if (!latestJson) return;
  try {
    await navigator.clipboard.writeText(latestJson);
    copyResultButton.textContent = "已复制";
  } catch {
    copyResultButton.textContent = "复制失败";
  }
  setTimeout(() => { copyResultButton.textContent = "复制 JSON"; }, 1600);
});

dragTestButton.addEventListener("click", async () => {
  if (dragTestBusy) return;
  const keyword = keywordInput.value.replace(/ /gu, "").trim();
  if (!keyword) {
    keywordInput.focus();
    showFailure(dragTestButton, dragTestBadge, dragTestResult, {
      code: "CNSE_KEYWORD_INVALID",
      message: "请输入单位名称",
    });
    return;
  }
  dragTestBusy = true;
  summary.hidden = true;
  showPending(dragTestButton, dragTestBadge, dragTestResult, "正在获取验证码、识别距离并查询数据…");
  try {
    const result = (await request("solve.start", { keyword })).payload;
    showSuccess(
      dragTestButton,
      dragTestBadge,
      dragTestResult,
      `查询完成：moveLength ${result.moveLength}；yHeight ${result.apiYHeight}；置信度 ${(result.confidence * 100).toFixed(1)}%；共 ${result.total} 条。`,
    );
    queryData.textContent = JSON.stringify({ total: result.total, rows: result.rows }, null, 2);
    latestJson = queryData.textContent;
    queryKeyword.textContent = `关键词：${result.keyword}`;
    metricDistance.textContent = String(result.moveLength);
    metricConfidence.textContent = `${(result.confidence * 100).toFixed(1)}%`;
    metricTotal.textContent = String(result.total);
    renderRows(result.rows);
    summary.hidden = false;
  } catch (error) {
    showFailure(dragTestButton, dragTestBadge, dragTestResult, error);
  } finally {
    dragTestBusy = false;
  }
});
