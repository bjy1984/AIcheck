(function (global, document) {
  const api = global.WorkbenchApi;
  if (!api) return;

  const role = /监检/.test(document.title) ? "inspection" : /施工方/.test(document.title) ? "contractor" : "";
  if (!role) return;

  const state = {
    role,
    projectId: api.PROJECT_ID,
    activeNodeId: role === "inspection" ? "24" : "16",
    activeNodeName: role === "inspection" ? "焊工资格证及持证合格项目" : "压力管道元件以及安全附件产品质量证明文件",
    selectedFile: role === "inspection" ? "焊工资格证-王建国.pdf" : "钢管质量证明书.pdf",
    zoom: 1,
    suggestionId: "AIS-24-20260625-01",
    reviewResult: "满足要求",
    reviewOpinion: "焊工资格证书真实有效，持证项目和项目焊接作业要求匹配。资格网站查询截图来源已人工确认。",
    aiSuggestionOpinion: "焊工王建国的焊工资格证编号 TS6J-2024-03158 在过程文件和外部查询结果中一致，证书有效期覆盖本项目施工周期，持证项目 GTAW、SMAW 与本项目焊接工艺要求一致，建议本节点审查结论为“满足要求”。需人工确认资格网站查询截图是否来自最新官方查询结果。"
  };
  let layerActionHandlers = [];

  function clean(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function endpoint(key, params) {
    return api.compileEndpoint(key, params || {}).descriptor;
  }

  function endpointHint(key, params) {
    return '<div class="api-hint"><span>后端预留接口</span><code>' + endpoint(key, params) + '</code></div>';
  }

  function ensureChrome() {
    if (!document.querySelector(".workbench-layer")) {
      const layer = document.createElement("div");
      layer.className = "workbench-layer";
      layer.innerHTML = [
        '<div class="workbench-backdrop" data-close-layer></div>',
        '<section class="workbench-modal" role="dialog" aria-modal="true" aria-labelledby="workbench-layer-title">',
        '  <button class="layer-close" type="button" data-close-layer>×</button>',
        '  <div class="layer-head"><div><h2 id="workbench-layer-title"></h2><div class="layer-sub"></div></div><span class="pill blue layer-badge"></span></div>',
        '  <div class="layer-body"></div>',
        '  <div class="layer-actions"></div>',
        '</section>'
      ].join("");
      document.body.appendChild(layer);
    }
    if (!document.querySelector(".toast-stack")) {
      const stack = document.createElement("div");
      stack.className = "toast-stack";
      document.body.appendChild(stack);
    }
  }

  function closeLayer() {
    const layer = document.querySelector(".workbench-layer");
    if (!layer) return;
    layer.classList.remove("open", "drawer");
    document.body.classList.remove("layer-open");
  }

  function openLayer(options) {
    ensureChrome();
    const layer = document.querySelector(".workbench-layer");
    layer.classList.toggle("drawer", options.kind === "drawer");
    layer.querySelector("#workbench-layer-title").textContent = options.title || "";
    layer.querySelector(".layer-sub").textContent = options.sub || "";
    layer.querySelector(".layer-badge").textContent = options.badge || (api.mode === "mock" ? "Mock 接口" : "Live 接口");
    layer.querySelector(".layer-body").innerHTML = options.body || "";

    const actions = layer.querySelector(".layer-actions");
    actions.innerHTML = "";
    layerActionHandlers = options.actions || [{ label: "关闭" }];
    layerActionHandlers.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn" + (item.variant ? " " + item.variant : "");
      button.textContent = item.label;
      button.dataset.layerActionIndex = String(index);
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (item.run) {
          item.run(button, layer);
        } else {
          closeLayer();
        }
      });
      actions.appendChild(button);
    });

    layer.classList.add("open");
    document.body.classList.add("layer-open");
  }

  function toast(title, detail, tone) {
    ensureChrome();
    const node = document.createElement("div");
    node.className = "toast" + (tone ? " " + tone : "");
    node.innerHTML = '<strong>' + escapeHtml(title) + '</strong>' + (detail ? '<span>' + escapeHtml(detail) + '</span>' : "");
    document.querySelector(".toast-stack").appendChild(node);
    global.setTimeout(() => node.classList.add("show"), 20);
    global.setTimeout(() => {
      node.classList.remove("show");
      global.setTimeout(() => node.remove(), 240);
    }, 3200);
  }

  async function runApi(button, request, after) {
    const original = button.textContent;
    button.disabled = true;
    button.classList.add("is-busy");
    button.textContent = "处理中...";
    try {
      const result = await request();
      if (after) after(result);
      toast(result.message || "操作已完成", result.endpoint || "", "success");
      closeLayer();
    } catch (error) {
      toast("操作失败", error.message || String(error), "danger");
    } finally {
      button.disabled = false;
      button.classList.remove("is-busy");
      button.textContent = original;
    }
  }

  function firstCellText(row) {
    const first = row && row.querySelector("td, th");
    return clean(first ? first.textContent : "");
  }

  function activeNodeLabel() {
    return state.activeNodeId + ". " + state.activeNodeName;
  }

  function setSelectedRow(row) {
    if (!row) return;
    const table = row.closest("table");
    if (table) table.querySelectorAll("tbody tr.selected").forEach((item) => item.classList.remove("selected"));
    row.classList.add("selected");
    const fileName = firstCellText(row);
    if (/\.(pdf|docx?|xlsx?|png|jpg|zip)$/i.test(fileName)) {
      state.selectedFile = fileName;
      updatePreview(fileName);
      toast("已选中文件", fileName);
    }
  }

  function updatePreview(fileName) {
    document.querySelectorAll(".preview-name").forEach((node) => {
      node.textContent = role === "contractor" ? "当前文件：" + fileName + " (预览)" : fileName;
    });
    const firstFileCell = Array.from(document.querySelectorAll(".right-card .table tr")).find((row) => clean(row.querySelector("th") && row.querySelector("th").textContent) === "文件名");
    if (firstFileCell && firstFileCell.querySelector("td")) firstFileCell.querySelector("td").textContent = fileName;
  }

  function selectNode(el) {
    const id = clean(el.children[0] ? el.children[0].textContent : "").replace(/[^\d]/g, "") || state.activeNodeId;
    const label = clean(el.querySelector(".tree-label") ? el.querySelector(".tree-label").textContent : el.textContent).replace(/^\d+\s*/, "");
    state.activeNodeId = id;
    state.activeNodeName = label || state.activeNodeName;
    document.querySelectorAll(".tree-node.active").forEach((node) => node.classList.remove("active"));
    if (el.classList.contains("tree-node")) el.classList.add("active");

    if (role === "inspection") {
      const sub = document.querySelector(".page-head .sub");
      if (sub) sub.textContent = "当前节点：" + activeNodeLabel() + " · 节点视角已切换 · 文件包与审查动作等待后端接口返回实时数据";
      const nodeHead = document.querySelector(".node-file-head small");
      if (nodeHead) nodeHead.textContent = activeNodeLabel();
    } else {
      const crumbs = document.querySelector(".crumbs");
      if (crumbs) crumbs.innerHTML = '当前位置：施工方 / 项目文件上传与文件库　　当前反馈节点：<span class="pill red">' + escapeHtml(activeNodeLabel()) + '</span>';
    }
    toast("已切换检测节点", activeNodeLabel());
  }

  function setTopStatus(text) {
    const topStatus = document.querySelector(".top-status");
    if (topStatus) topStatus.textContent = text;
  }

  function updateMetric(label, value, tone) {
    const card = Array.from(document.querySelectorAll(".metric")).find((item) => clean(item.querySelector(".metric-label") && item.querySelector(".metric-label").textContent) === label);
    if (!card) return;
    const metricValue = card.querySelector(".metric-value");
    metricValue.textContent = value;
    metricValue.className = "metric-value" + (tone ? " " + tone : "");
  }

  function controlValue(selector, fallback) {
    const control = document.querySelector(selector);
    if (!control) return fallback || "";
    return typeof control.value === "string" ? control.value.trim() : clean(control.textContent);
  }

  function optionList(values, selected) {
    return values.map((value) => '<option' + (value === selected ? " selected" : "") + ">" + escapeHtml(value) + "</option>").join("");
  }

  function readReviewDraft() {
    state.reviewResult = controlValue("[data-review-result]", state.reviewResult);
    state.reviewOpinion = controlValue("[data-review-opinion]", state.reviewOpinion);
    return {
      result: state.reviewResult,
      opinion: state.reviewOpinion
    };
  }

  function readAiSuggestionDraft() {
    state.aiSuggestionOpinion = controlValue("[data-ai-suggestion]", state.aiSuggestionOpinion);
    return state.aiSuggestionOpinion;
  }

  function setReviewDraft(result, opinion) {
    const resultControl = document.querySelector("[data-review-result]");
    const opinionControl = document.querySelector("[data-review-opinion]");
    state.reviewResult = result || state.reviewResult;
    state.reviewOpinion = opinion || state.reviewOpinion;
    if (resultControl) resultControl.value = state.reviewResult;
    if (opinionControl) opinionControl.value = state.reviewOpinion;
  }

  function setAiSuggestionDraft(opinion) {
    const suggestionControl = document.querySelector("[data-ai-suggestion]");
    state.aiSuggestionOpinion = opinion || state.aiSuggestionOpinion;
    if (suggestionControl) suggestionControl.value = state.aiSuggestionOpinion;
  }

  function appendFileRow(fileName, nodes, statusText) {
    const tables = Array.from(document.querySelectorAll(".card"));
    const libraryCard = tables.find((card) => /项目文件库/.test(clean(card.querySelector(".card-head h2") && card.querySelector(".card-head h2").textContent)));
    const body = libraryCard && libraryCard.querySelector("tbody");
    if (!body) return;
    const row = document.createElement("tr");
    row.innerHTML = [
      "<td>" + escapeHtml(fileName) + "</td>",
      "<td>补正附件</td>",
      "<td>V1</td>",
      '<td><span class="pill blue">已上传</span></td>',
      '<td><span class="pill orange">' + escapeHtml(statusText || "待提交") + "</span></td>",
      "<td>待识别</td>",
      "<td>李工</td>",
      "<td>1条</td>",
      "<td><a>选择挂载节点</a></td>"
    ].join("");
    body.prepend(row);
    row.classList.add("selected");
    updatePreview(fileName);
    if (nodes) toast("文件已加入项目文件库", fileName + " -> " + nodes);
  }

  function checkboxList(items, name, checkedIndexes) {
    const checked = checkedIndexes || [];
    return '<div class="check-list">' + items.map((item, index) => {
      const id = name + "-" + index;
      return '<label for="' + id + '"><input id="' + id + '" type="checkbox" ' + (checked.includes(index) ? "checked" : "") + ' /> <span>' + escapeHtml(item) + '</span></label>';
    }).join("") + "</div>";
  }

  function field(label, html) {
    return '<label class="field"><span>' + escapeHtml(label) + '</span>' + html + "</label>";
  }

  function handleCommon(action) {
    if (action === "global-search") {
      openLayer({
        title: "全局搜索",
        sub: "按文件、检测节点、人员、标准条款和反馈内容统一检索。",
        body: [
          '<div class="form-grid two">',
          field("搜索关键词", '<input value="' + (role === "inspection" ? "焊工资格 TS6J-2024" : "钢管质量证明书 炉批号") + '" />'),
          field("搜索范围", '<select><option>本项目全部资料</option><option>当前节点</option><option>本单位资料</option></select>'),
          "</div>",
          '<table class="table"><thead><tr><th>命中对象</th><th>类型</th><th>状态</th><th>可执行动作</th></tr></thead><tbody>',
          '<tr><td>' + escapeHtml(state.selectedFile) + '</td><td>文件</td><td><span class="pill blue">已命中</span></td><td>打开预览 / 定位证据</td></tr>',
          '<tr><td>' + escapeHtml(activeNodeLabel()) + '</td><td>检测节点</td><td><span class="pill orange">当前节点</span></td><td>切换节点 / 查看文件包</td></tr>',
          '<tr><td>TSG Z6002 焊工资格规则</td><td>标准条款</td><td><span class="pill green">可引用</span></td><td>查看条款</td></tr>',
          "</tbody></table>",
          endpointHint("getWorkbenchSummary", { role })
        ].join(""),
        actions: [{ label: "定位当前命中", variant: "primary", run: (button) => runApi(button, () => api.getWorkbenchSummary(role)) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "todo-center" || action === "message-center") {
      const isTodo = action === "todo-center";
      openLayer({
        title: isTodo ? "待办中心" : "消息中心",
        sub: isTodo ? "聚合当前角色可处理事项，点击行可定位到工作台节点。" : "展示退回、提交、报告和系统提醒消息。",
        body: [
          '<table class="table"><thead><tr><th>事项</th><th>关联对象</th><th>状态</th><th>下一步</th></tr></thead><tbody>',
          '<tr class="selected"><td>' + (role === "inspection" ? "焊工资格节点待确认" : "材料质量证明文件需补正") + '</td><td>' + escapeHtml(activeNodeLabel()) + '</td><td><span class="pill orange">待处理</span></td><td>定位节点</td></tr>',
          '<tr><td>报告复核提醒</td><td>项目报告草稿</td><td><span class="pill blue">提醒</span></td><td>打开报告复核</td></tr>',
          '<tr><td>接口审计记录</td><td>最近 24 小时操作</td><td><span class="pill green">正常</span></td><td>查看详情</td></tr>',
          "</tbody></table>",
          endpointHint("getWorkbenchSummary", { role })
        ].join(""),
        actions: [{ label: "定位到当前节点", variant: "primary", run: (button) => runApi(button, () => api.getNodePackage(state.activeNodeId)) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "user-menu") {
      const endpoints = api.listReservedEndpoints().slice(0, 10).map((item) => '<tr><td>' + item.key + '</td><td><code>' + escapeHtml(item.descriptor) + '</code></td></tr>').join("");
      openLayer({
        title: "用户与接口模式",
        sub: "当前页面使用前端 mock 数据驱动，后端接口路径已集中预留。",
        body: [
          '<div class="sub-grid">',
          '<div class="mini-panel"><h4>当前角色</h4><p>' + (role === "inspection" ? "监检员 张工：审查、退回、报告生成/复核。" : "施工方 李工：上传、挂载、补正、提交。") + '</p></div>',
          '<div class="mini-panel"><h4>接口模式</h4><p>' + (api.mode === "mock" ? "Mock 模式，不请求真实后端。" : "Live 模式，按预留接口请求后端。") + '</p></div>',
          '<div class="mini-panel"><h4>项目权限</h4><p>项目级资料可见，动作权限按角色收敛。</p></div>',
          "</div>",
          '<table class="table compact"><thead><tr><th style="width:230px;">接口键</th><th>预留路径</th></tr></thead><tbody>' + endpoints + "</tbody></table>"
        ].join(""),
        actions: [{ label: "关闭", variant: "primary" }]
      });
      return true;
    }
    if (action === "node-detail") {
      openLayer({
        kind: "drawer",
        title: "节点详情",
        sub: activeNodeLabel(),
        body: [
          '<div class="sub-grid">',
          '<div class="mini-panel"><h4>节点状态</h4><p>' + (role === "inspection" ? "待人工确认，AI 建议不可自动审批。" : "施工方可查看反馈并提交补正。") + '</p></div>',
          '<div class="mini-panel"><h4>文件包</h4><p>节点文件包来自项目文件库与节点挂载关系，不等同于树节点。</p></div>',
          '<div class="mini-panel"><h4>权限边界</h4><p>' + (role === "inspection" ? "可挂载证据、保存意见、退回补正、发起报告复核。" : "可上传本单位文件、选择一个或多个节点挂载。") + '</p></div>',
          "</div>",
          endpointHint("getNodePackage", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "刷新节点文件包", variant: "primary", run: (button) => runApi(button, () => api.getNodePackage(state.activeNodeId)) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "file-detail" || action === "feedback-detail") {
      openLayer({
        kind: "drawer",
        title: action === "feedback-detail" ? "反馈详情" : "文件详情",
        sub: state.selectedFile,
        body: [
          '<table class="table"><tbody>',
          '<tr><th>文件</th><td>' + escapeHtml(state.selectedFile) + '</td></tr>',
          '<tr><th>关联节点</th><td>' + escapeHtml(activeNodeLabel()) + '</td></tr>',
          '<tr><th>版本</th><td>V2，保留历史版本与提交快照</td></tr>',
          '<tr><th>反馈/证据</th><td>' + (role === "inspection" ? "11 条证据链可定位。" : "炉批号与材料清单不一致，需补充复验报告。") + '</td></tr>',
          "</tbody></table>",
          endpointHint("getNodePackage", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "定位到预览", variant: "primary", run: (button) => runApi(button, () => api.getNodePackage(state.activeNodeId)) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "preview-zoom-in" || action === "preview-zoom-out") {
      state.zoom = action === "preview-zoom-in" ? Math.min(1.4, state.zoom + 0.1) : Math.max(0.75, state.zoom - 0.1);
      document.querySelectorAll(".doc-paper").forEach((paper) => {
        paper.style.transform = "scale(" + state.zoom.toFixed(2) + ")";
        paper.style.transformOrigin = "top center";
      });
      toast("预览缩放", Math.round(state.zoom * 100) + "%");
      return true;
    }
    if (action === "download-center") {
      toast("下载任务已创建", state.selectedFile + "，当前为静态原型模拟。");
      return true;
    }
    if (action === "refresh-state") {
      toast("状态已刷新", "已从 mock 接口同步当前工作台摘要。");
      api.getWorkbenchSummary(role);
      return true;
    }
    return false;
  }

  function handleContractor(action) {
    if (action === "contractor-upload") {
      openLayer({
        title: "批量上传文件",
        sub: "文件先进入项目级文件库，再选择一个或多个检测节点形成挂载关系。",
        body: [
          '<div class="upload-dialog-zone">点击选择或拖拽文件到此处<br><span>静态原型会模拟上传 3 个文件并生成上传会话</span></div>',
          '<div class="form-grid two">',
          field("来源单位", '<input value="中石化安装有限公司" />'),
          field("默认用途", '<select><option>补正附件</option><option>原始提交</option><option>整改说明</option><option>证明材料</option></select>'),
          "</div>",
          checkboxList(["16. 质量证明文件", "18. 材料复验报告、无损检测报告", "23. 阀门施工资料", "24. 焊工资格证及持证合格项目"], "upload-node", [0, 1]),
          endpointHint("createUploadSession")
        ].join(""),
        actions: [
          { label: "保存草稿", run: (button) => runApi(button, () => api.saveDraft({ activeNodeId: state.activeNodeId, file: state.selectedFile })) },
          { label: "模拟上传并入库", variant: "primary", run: (button) => runApi(button, () => api.createUploadSession({ files: ["炉批号差异说明.pdf", "材料复验报告-补正.pdf", "现场照片-材料标识.zip"], defaultNodes: ["16", "18"] }), () => {
            appendFileRow("材料复验报告-补正.pdf", "16,18", "待提交");
            updateMetric("本批文件", "15");
            updateMetric("已选择挂载", "10", "green");
          }) },
          { label: "关闭" }
        ]
      });
      return true;
    }
    if (action === "contractor-mount-node") {
      openLayer({
        title: "选择挂载节点",
        sub: "同一文件可以挂载到多个检测节点，每条挂载关系独立记录用途、资料项和补正轮次。",
        body: [
          '<div class="selected-object">当前文件：<strong>' + escapeHtml(state.selectedFile) + '</strong></div>',
          checkboxList(["16. 压力管道元件以及安全附件产品质量证明文件", "18. 材料复验报告、无损检测报告", "21. 材料标志移植", "23. 阀门的施工资料和耐压试验记录（报告）"], "mount-node", [0, 1]),
          '<div class="form-grid two">',
          field("资料项", '<input value="材料复验报告 / 炉批号差异说明" />'),
          field("文件用途", '<select><option>补正附件</option><option>原始提交</option><option>整改说明</option></select>'),
          "</div>",
          endpointHint("bindDocumentsToNodes")
        ].join(""),
        actions: [
          { label: "保存挂载关系", variant: "primary", run: (button) => runApi(button, () => api.bindDocumentsToNodes({ documentName: state.selectedFile, nodeIds: ["16", "18"], usage: "补正附件" }), () => updateMetric("已选择挂载", "9", "green")) },
          { label: "关闭" }
        ]
      });
      return true;
    }
    if (action === "contractor-submit") {
      openLayer({
        title: "提交本批文件及挂载关系",
        sub: "提交对象是项目文件版本和节点挂载关系；提交后不可物理删除，只能补正或撤回未提交项。",
        body: [
          '<table class="table compact"><tbody>',
          '<tr><th>提交批次</th><td>SUB-DRAFT-20260625-003</td></tr>',
          '<tr><th>提交文件</th><td>12 个文件，8 个已挂载，3 个未挂载仅保存草稿</td></tr>',
          '<tr><th>补正节点</th><td>16. 产品质量证明文件；18. 材料复验报告、无损检测报告</td></tr>',
          '<tr><th>提交后状态</th><td><span class="pill blue">AI 预审中</span>，等待监检复核</td></tr>',
          "</tbody></table>",
          endpointHint("submitContractorBatch")
        ].join(""),
        actions: [
          { label: "确认提交", variant: "primary", run: (button) => runApi(button, () => api.submitContractorBatch({ batchId: "SUB-DRAFT-20260625-003", activeNodeId: state.activeNodeId }), (result) => {
            setTopStatus(result.nextStatus || "AI 预审中");
            updateMetric("未挂载", "2", "orange");
          }) },
          { label: "关闭" }
        ]
      });
      return true;
    }
    if (action === "draft-save") {
      openLayer({
        title: "保存草稿",
        sub: "草稿保留文件、用途和当前挂载选择，不触发监检审查。",
        body: endpointHint("saveDraft"),
        actions: [{ label: "保存草稿", variant: "primary", run: (button) => runApi(button, () => api.saveDraft({ activeNodeId: state.activeNodeId, selectedFile: state.selectedFile })) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "withdraw-submit") {
      openLayer({
        title: "撤回未提交文件",
        sub: "仅允许撤回未提交或草稿状态文件；已提交文件不做物理删除。",
        body: [
          '<div class="note">当前选中文件：' + escapeHtml(state.selectedFile) + '。若该文件已进入正式提交快照，系统只会记录撤回申请。</div>',
          endpointHint("withdrawSubmissionItem", { submissionId: "SUB-DRAFT-20260625-003" })
        ].join(""),
        actions: [{ label: "确认撤回", variant: "primary", run: (button) => runApi(button, () => api.withdrawSubmissionItem("SUB-DRAFT-20260625-003", { fileName: state.selectedFile })) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "file-history") {
      openLayer({
        kind: "drawer",
        title: "历史版本",
        sub: state.selectedFile,
        body: [
          '<table class="table"><thead><tr><th>版本</th><th>来源</th><th>提交状态</th><th>说明</th></tr></thead><tbody>',
          '<tr class="selected"><td>V2</td><td>施工方 李工</td><td><span class="pill red">需补正</span></td><td>炉批号字段与材料清单不一致。</td></tr>',
          '<tr><td>V1</td><td>施工方 李工</td><td><span class="pill blue">已提交</span></td><td>原始上传版本。</td></tr>',
          "</tbody></table>"
        ].join(""),
        actions: [{ label: "关闭", variant: "primary" }]
      });
      return true;
    }
    if (action === "feedback-correction") {
      openLayer({
        title: "提交补正反馈",
        sub: "针对监检意见提交整改说明、补正附件和新的节点挂载关系。",
        body: [
          '<table class="table compact"><tbody>',
          '<tr><th>反馈节点</th><td>' + escapeHtml(activeNodeLabel()) + '</td></tr>',
          '<tr><th>监检意见</th><td>钢管质量证明书中炉批号与材料清单不一致。</td></tr>',
          "</tbody></table>",
          field("整改说明", '<textarea>已补充材料复验报告，并说明材料清单录入漏写尾号。</textarea>'),
          checkboxList(["炉批号差异说明.pdf", "材料复验报告.pdf", "现场材料标识照片.zip"], "feedback-file", [0, 1]),
          endpointHint("submitRectification")
        ].join(""),
        actions: [{ label: "提交补正反馈", variant: "primary", run: (button) => runApi(button, () => api.submitRectification({ nodeId: state.activeNodeId, description: "已补充材料复验报告，并说明材料清单录入漏写尾号。", files: ["炉批号差异说明.pdf", "材料复验报告.pdf"] }), (result) => {
          setTopStatus(result.nextStatus || "待复审");
          updateMetric("需补正", "0", "green");
        }) }, { label: "关闭" }]
      });
      return true;
    }
    return false;
  }

  function handleInspection(action) {
    if (action === "ai-recheck") {
      openLayer({
        title: "重新核验",
        sub: "重新运行当前节点的业务审查链路，结果仍为监检人员审查参考。",
        body: [
          '<div class="review-chain compact-chain">',
          '<div class="review-step"><div class="step-no">1</div><div><div class="step-title">重新读取过程文件</div><div class="step-desc">获取节点文件包最新版本和外部查询截图。</div></div><span class="pill blue">待运行</span></div>',
          '<div class="review-step"><div class="step-no">2</div><div><div class="step-title">执行规则链路</div><div class="step-desc">证书真实性、有效期、持证项目、跨文件一致性。</div></div><span class="pill blue">待运行</span></div>',
          '<div class="review-step"><div class="step-no">3</div><div><div class="step-title">生成建议结果</div><div class="step-desc">形成建议结论、证据链和人工确认项。</div></div><span class="pill blue">待运行</span></div>',
          "</div>",
          endpointHint("recheckNode", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "开始重新核验", variant: "primary", run: (button) => runApi(button, () => api.recheckNode(state.activeNodeId, { selectedFile: state.selectedFile }), (result) => updateMetric("证据引用", (result.evidenceLinks || 12) + " 条")) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "rule-version") {
      openLayer({
        kind: "drawer",
        title: "规则版本",
        sub: activeNodeLabel(),
        body: [
          '<table class="table"><tbody>',
          '<tr><th>规则模板</th><td>Welder-Qualification-B-v2.1</td></tr>',
          '<tr><th>业务 Prompt</th><td>24-焊工资格-v1.5</td></tr>',
          '<tr><th>输入资料</th><td>资格证、焊工名册、焊接工艺卡、施焊记录、外部查询结果</td></tr>',
          '<tr><th>输出约束</th><td>核验步骤、证据引用、建议结论、人工确认项</td></tr>',
          "</tbody></table>",
          endpointHint("getRuleVersion", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "刷新规则版本", variant: "primary", run: (button) => runApi(button, () => api.getRuleVersion(state.activeNodeId)) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "copy-conclusion") {
      const text = "建议结论：满足要求；建议意见：" + readAiSuggestionDraft();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => toast("业务结论已复制", text), () => toast("复制内容", text));
      } else {
        toast("复制内容", text);
      }
      return true;
    }
    if (action === "inspection-mount-file") {
      openLayer({
        title: "监检挂载文件",
        sub: "监检人员可从项目文件库选择文件挂载到当前节点，也可挂载本人上传的现场证据。",
        body: [
          checkboxList(["资格网站查询截图.png", "焊工资格证-赵强.pdf", "监检现场照片.zip", "项目施工计划.pdf"], "inspection-file", [0]),
          checkboxList([activeNodeLabel(), "25. 焊接（粘接）工艺文件", "29. 施焊参数、施焊记录、焊缝标识"], "inspection-node", [0]),
          endpointHint("mountInspectionFile", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "保存挂载", variant: "primary", run: (button) => runApi(button, () => api.mountInspectionFile(state.activeNodeId, { files: ["资格网站查询截图.png"], nodeIds: [state.activeNodeId] })) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "inspection-upload") {
      openLayer({
        title: "上传监检资料",
        sub: "上传现场检查照片、补充说明或外部核验截图，并挂载到当前节点。",
        body: [
          '<div class="upload-dialog-zone">上传监检现场资料<br><span>模拟生成附件版本和 EvidenceLink</span></div>',
          '<div class="form-grid two">',
          field("资料类型", '<select><option>外部查询截图</option><option>现场照片</option><option>监检说明</option></select>'),
          field("挂载节点", '<input value="' + escapeHtml(activeNodeLabel()) + '" />'),
          "</div>",
          endpointHint("uploadInspectionAttachment", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "上传并挂载", variant: "primary", run: (button) => runApi(button, () => api.uploadInspectionAttachment(state.activeNodeId, { fileName: "资格网站查询截图-最新.png", type: "外部查询截图" })) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "inspection-opinion") {
      const draft = readReviewDraft();
      openLayer({
        title: "保存审查意见",
        sub: "人工审查结论由监检人员保存，AI 输出只作为建议和证据引用。",
        body: [
          '<div class="form-grid two">',
          field("检查结果", '<select data-layer-review-result>' + optionList(["满足要求", "需补正", "不适用"], draft.result) + "</select>"),
          field("人工确认项", '<select><option>资格网站截图来源已确认</option><option>保留人工确认</option></select>'),
          "</div>",
          field("审查意见", '<textarea data-layer-review-opinion>' + escapeHtml(draft.opinion) + "</textarea>"),
          endpointHint("saveInspectionOpinion", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{
          label: "保存审查意见",
          variant: "primary",
          run: (button, layer) => {
            const result = controlValue("[data-layer-review-result]", draft.result);
            const opinion = controlValue("[data-layer-review-opinion]", draft.opinion);
            if (!opinion) {
              toast("请填写审查意见", "审查意见不能为空。", "danger");
              return;
            }
            setReviewDraft(result, opinion);
            runApi(button, () => api.saveInspectionOpinion(state.activeNodeId, { result, opinion }), () => {
              updateMetric("待人工确认", "0 项", "green");
            });
          }
        }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "ai-adopt" || action === "ai-reject") {
      const adopt = action === "ai-adopt";
      const suggestionOpinion = readAiSuggestionDraft();
      openLayer({
        title: adopt ? "采纳 AI 建议" : "驳回 AI 建议",
        sub: adopt ? "采纳后写入审查意见草稿，仍需人工最终确认。" : "驳回后保留 AI 建议与人工意见差异记录。",
        body: [
          '<div class="note">' + (adopt ? "建议结论为“满足要求”，采纳后不会自动完成审批。" : "请填写驳回原因，便于后续审计和规则优化。") + '</div>',
          adopt ? field("写入审查意见草稿", '<textarea data-layer-ai-adopt-opinion>' + escapeHtml(suggestionOpinion) + "</textarea>") : field("驳回原因", '<textarea data-layer-ai-reject-reason>外部查询截图来源不足，需施工方补充最新查询结果。</textarea>'),
          adopt ? field("采纳说明", '<textarea data-layer-ai-adopt-reason>AI 建议与人工核验一致，采纳为审查意见草稿，后续仍由监检人员保存确认。</textarea>') : "",
          endpointHint(adopt ? "adoptAiSuggestion" : "rejectAiSuggestion", { nodeId: state.activeNodeId, suggestionId: state.suggestionId })
        ].join(""),
        actions: [{
          label: adopt ? "确认采纳" : "确认驳回",
          variant: adopt ? "primary" : "orange",
          run: (button) => {
            if (adopt) {
              const opinion = controlValue("[data-layer-ai-adopt-opinion]", suggestionOpinion);
              const reason = controlValue("[data-layer-ai-adopt-reason]", "与人工核验一致");
              if (!opinion) {
                toast("请填写采纳后的审查意见草稿", "草稿不能为空。", "danger");
                return;
              }
              setReviewDraft("满足要求", opinion);
              runApi(button, () => api.adoptAiSuggestion(state.activeNodeId, state.suggestionId, { result: "满足要求", opinion, reason }));
              return;
            }
            const reason = controlValue("[data-layer-ai-reject-reason]", "");
            if (!reason) {
              toast("请填写驳回原因", "驳回 AI 建议需要保留原因。", "danger");
              return;
            }
            runApi(button, () => api.rejectAiSuggestion(state.activeNodeId, state.suggestionId, { reason }));
          }
        }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "return-correction") {
      openLayer({
        title: "退回补正",
        sub: "生成补正通知，责任单位在施工方工作台提交补正反馈。",
        body: [
          '<div class="form-grid two">',
          field("责任单位", '<select><option>施工方</option><option>无损检测机构</option></select>'),
          field("补正截止", '<input value="2026-06-28 18:00" />'),
          "</div>",
          field("补正要求", '<textarea>请补充最新资格网站查询截图，并说明截图来源和查询时间。</textarea>'),
          checkboxList(["当前节点文件包", "资格网站查询截图.png", "焊工名册.xlsx"], "return-evidence", [0, 1]),
          endpointHint("returnCorrection", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "生成退回补正", variant: "orange", run: (button) => runApi(button, () => api.returnCorrection(state.activeNodeId, { responsibleOrg: "施工方", deadline: "2026-06-28 18:00", requirement: "请补充最新资格网站查询截图。" }), (result) => setTopStatus(result.nextStatus || "退回补正中")) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "report-review") {
      openLayer({
        title: "报告生成/复核",
        sub: "汇总项目资料、检查结果、审查意见和证据链，生成可编辑报告草稿。",
        body: [
          '<table class="table compact"><tbody>',
          '<tr><th>报告范围</th><td>当前项目全部已审查节点，包含 A/B/C 项目。</td></tr>',
          '<tr><th>当前节点</th><td>' + escapeHtml(activeNodeLabel()) + ' 已纳入报告证据链。</td></tr>',
          '<tr><th>复核要求</th><td>监检人员在报告生成/复核节点完成确认，可退回补正。</td></tr>',
          "</tbody></table>",
          endpointHint("startReportReview", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "生成报告草稿", variant: "primary", run: (button) => runApi(button, () => api.startReportReview(state.activeNodeId, { includeEvidence: true }), (result) => setTopStatus(result.nextStatus || "报告生成/复核中")) }, { label: "关闭" }]
      });
      return true;
    }
    if (action === "evidence-locator" || action === "evidence-chain" || action === "standard-reference" || action === "date-compare") {
      const titleMap = {
        "evidence-locator": "证据定位",
        "evidence-chain": "证据链",
        "standard-reference": "标准依据",
        "date-compare": "日期比对"
      };
      openLayer({
        kind: "drawer",
        title: titleMap[action],
        sub: activeNodeLabel(),
        body: [
          '<table class="table"><thead><tr><th>核验项</th><th>证据/依据</th><th>结论</th></tr></thead><tbody>',
          '<tr class="selected"><td>证书真实性</td><td>证书第 1 页；资格网站查询截图区域 A</td><td><span class="pill green">通过</span></td></tr>',
          '<tr><td>有效期覆盖</td><td>2024-04-12 至 2028-04-11 覆盖项目周期</td><td><span class="pill green">通过</span></td></tr>',
          '<tr><td>持证项目适配</td><td>TSG Z6002；节点资料说明；工艺卡第 1 页</td><td><span class="pill green">通过</span></td></tr>',
          "</tbody></table>",
          endpointHint("getEvidenceChain", { nodeId: state.activeNodeId })
        ].join(""),
        actions: [{ label: "刷新证据链", variant: "primary", run: (button) => runApi(button, () => api.getEvidenceChain(state.activeNodeId)) }, { label: "关闭" }]
      });
      return true;
    }
    return false;
  }

  function actionFromTrigger(trigger) {
    const label = clean(trigger.textContent) || clean(trigger.getAttribute("title"));

    if (trigger.classList.contains("global-search")) return "global-search";
    if (trigger.classList.contains("upload-box")) return "contractor-upload";
    if (trigger.classList.contains("tree-node") || trigger.classList.contains("tree-group") || trigger.classList.contains("tree-root")) return "node-detail";
    if (trigger.classList.contains("section-tools")) {
      if (/反馈/.test(label)) return "feedback-detail";
      if (/↻/.test(label)) return "refresh-state";
      return "node-detail";
    }
    if (trigger.closest(".top-actions")) {
      if (/待办/.test(label)) return "todo-center";
      if (/消息/.test(label)) return "message-center";
      if (/监检员|施工方|张工|李工/.test(label)) return "user-menu";
    }

    if (/放大/.test(label)) return "preview-zoom-in";
    if (/缩小/.test(label)) return "preview-zoom-out";
    if (/下载/.test(label)) return "download-center";
    if (/定位证据|定位反馈|定位意见/.test(label)) return "evidence-locator";
    if (/查看证据链/.test(label)) return "evidence-chain";
    if (/查看日期比对/.test(label)) return "date-compare";
    if (/查看条款|标准依据/.test(label)) return "standard-reference";

    if (/批量上传文件|选择文件|上传补正附件/.test(label)) return "contractor-upload";
    if (/选择挂载节点|未挂载文件挂载/.test(label)) return "contractor-mount-node";
    if (/提交本批文件及挂载关系|提交选中文件及挂载关系|提交选中文件|^提交$/.test(label)) return "contractor-submit";
    if (/保存草稿/.test(label)) return "draft-save";
    if (/撤回未提交/.test(label)) return "withdraw-submit";
    if (/查看历史版本/.test(label)) return "file-history";
    if (/补正反馈/.test(label)) return "feedback-correction";
    if (/查看\/替换|查看反馈|关联意见|查看$/.test(label)) return /反馈|意见/.test(label) ? "feedback-detail" : "file-detail";

    if (/重新核验|重新推理/.test(label)) return "ai-recheck";
    if (/查看规则版本/.test(label)) return "rule-version";
    if (/复制业务结论|复制结论/.test(label)) return "copy-conclusion";
    if (/挂载文件/.test(label)) return "inspection-mount-file";
    if (/上传监检资料/.test(label)) return "inspection-upload";
    if (/保存审查意见|保存意见/.test(label)) return "inspection-opinion";
    if (/采纳 AI 建议|采纳结果/.test(label)) return "ai-adopt";
    if (/驳回 AI 建议|驳回结果/.test(label)) return "ai-reject";
    if (/退回补正/.test(label)) return "return-correction";
    if (/报告生成\s*\/\s*复核|报告生成\/复核/.test(label)) return "report-review";

    return "";
  }

  function handleTrigger(trigger, event) {
    if (trigger.classList.contains("tree-node") || trigger.classList.contains("tree-group") || trigger.classList.contains("tree-root")) {
      selectNode(trigger);
      event.preventDefault();
      event.stopPropagation();
      return true;
    }

    const action = actionFromTrigger(trigger);
    if (!action) return false;

    const handled = handleCommon(action) || (role === "inspection" ? handleInspection(action) : handleContractor(action));
    if (!handled) return false;
    event.preventDefault();
    event.stopPropagation();
    return true;
  }

  function markControls() {
    const selector = [
      "button",
      "a:not([href])",
      ".global-search",
      ".top-actions > span",
      ".tree-node",
      ".tree-group",
      ".tree-root",
      ".section-tools",
      ".upload-box"
    ].join(",");
    document.querySelectorAll(selector).forEach((el) => {
      el.classList.add("workbench-clickable");
      const action = actionFromTrigger(el);
      if (action) el.setAttribute("title", "工作台交互：" + action);
    });
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest(".project-switch-layer, [data-project-switcher]")) return;

    if (event.target.closest("[data-close-layer]")) {
      event.preventDefault();
      event.stopPropagation();
      closeLayer();
      return;
    }

    const layerActionButton = event.target.closest(".layer-actions button[data-layer-action-index]");
    if (layerActionButton) {
      const item = layerActionHandlers[Number(layerActionButton.dataset.layerActionIndex)];
      event.preventDefault();
      event.stopPropagation();
      if (!item) return;
      if (item.run) {
        item.run(layerActionButton, document.querySelector(".workbench-layer"));
      } else {
        closeLayer();
      }
      return;
    }

    const row = event.target.closest("tbody tr");
    if (row && !event.target.closest("button, a, input, textarea, select, label")) {
      setSelectedRow(row);
    }

    const trigger = event.target.closest([
      "button",
      "a:not([href])",
      ".global-search",
      ".top-actions > span",
      ".tree-node",
      ".tree-group",
      ".tree-root",
      ".section-tools",
      ".upload-box"
    ].join(","));

    if (trigger) handleTrigger(trigger, event);
  }, true);

  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-review-opinion]")) state.reviewOpinion = event.target.value;
    if (event.target.matches("[data-ai-suggestion]")) state.aiSuggestionOpinion = event.target.value;
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-review-result]")) state.reviewResult = event.target.value;
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeLayer();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", markControls);
  } else {
    markControls();
  }
})(window, document);
