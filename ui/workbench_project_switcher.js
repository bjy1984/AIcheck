(function (global, document) {
  const STORAGE_PREFIX = "workbench.currentProject.";

  const PROJECTS = [
    {
      id: "P-2026-HDCP-001",
      name: "华东成品油管道改造工程",
      org: "中石化安装有限公司",
      owner: "华东管网建设公司",
      region: "华东",
      updatedAt: "今天 09:30",
      statuses: { inspection: "监检审查中", contractor: "资料提交中" },
      nodes: { inspection: 24, contractor: 16 },
      todo: { inspection: 12, contractor: 12 },
      messages: { inspection: 7, contractor: 7 },
      stats: { review: 8, correction: 3, overdue: 1 }
    },
    {
      id: "P-2026-GDLNG-002",
      name: "广东 LNG 支线改造工程",
      org: "粤海安装工程有限公司",
      owner: "南方能源管网公司",
      region: "华南",
      updatedAt: "今天 11:10",
      statuses: { inspection: "退回补正中", contractor: "退回补正中" },
      nodes: { inspection: 16, contractor: 16 },
      todo: { inspection: 9, contractor: 5 },
      messages: { inspection: 4, contractor: 6 },
      stats: { review: 4, correction: 5, overdue: 2 }
    },
    {
      id: "P-2026-SXCHEM-003",
      name: "山西化工园区蒸汽管道工程",
      org: "晋北管道建设有限公司",
      owner: "山西化工园区管委会",
      region: "华北",
      updatedAt: "昨天 17:45",
      statuses: { inspection: "AI 预审中", contractor: "AI 预审中" },
      nodes: { inspection: 59, contractor: 59 },
      todo: { inspection: 6, contractor: 3 },
      messages: { inspection: 2, contractor: 2 },
      stats: { review: 6, correction: 1, overdue: 0 }
    },
    {
      id: "P-2025-NJARCH-018",
      name: "南京老厂区管廊改造工程",
      org: "江北设备安装有限公司",
      owner: "南京工业资产运营公司",
      region: "华东",
      updatedAt: "2026-06-20",
      statuses: { inspection: "已归档", contractor: "已归档" },
      nodes: { inspection: 68, contractor: 68 },
      todo: { inspection: 0, contractor: 0 },
      messages: { inspection: 1, contractor: 1 },
      stats: { review: 0, correction: 0, overdue: 0 }
    }
  ];

  function roleFromPage() {
    const title = document.title || "";
    if (/施工方/.test(title)) return "contractor";
    if (/监检/.test(title)) return "inspection";
    return "inspection";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function projectById(id) {
    return PROJECTS.find((project) => project.id === id) || PROJECTS[0];
  }

  function statusPill(status) {
    if (/退回|补正/.test(status)) return "orange";
    if (/归档/.test(status)) return "green";
    if (/AI/.test(status)) return "blue";
    return "blue";
  }

  function nodeLabel(nodeId) {
    const node = global.WorkbenchProjectTree && global.WorkbenchProjectTree.findNode(nodeId);
    return node ? node.id + ". " + node.name : String(nodeId);
  }

  function setNoticeCounts(project, role) {
    const dots = document.querySelectorAll(".top-actions .notice-dot");
    if (dots[0]) dots[0].textContent = project.todo[role];
    if (dots[1]) dots[1].textContent = project.messages[role];
  }

  function updateProjectContext(project, role) {
    const nameTarget = document.querySelector("[data-project-name]");
    const trigger = document.querySelector("[data-project-switcher]");
    const status = document.querySelector(".top-status");
    const nodeId = project.nodes[role];
    const node = global.WorkbenchProjectTree && global.WorkbenchProjectTree.findNode(nodeId);

    if (nameTarget) nameTarget.textContent = project.name;
    if (trigger) {
      trigger.dataset.currentProject = project.id;
      trigger.setAttribute("title", "切换项目：" + project.name);
    }
    if (status) status.textContent = project.statuses[role];
    setNoticeCounts(project, role);

    document.querySelectorAll("[data-project-tree]").forEach((tree) => {
      tree.dataset.projectName = project.name;
      tree.dataset.activeNode = String(nodeId);
    });
    if (global.WorkbenchProjectTree) global.WorkbenchProjectTree.renderAll();

    if (role === "inspection") {
      const sub = document.querySelector(".page-head .sub");
      if (sub && node) {
        sub.textContent = "当前项目：" + project.name + " · 当前节点：" + nodeLabel(nodeId) + " · " + node.type + "类节点 · 文件包等待后端接口返回实时数据";
      }
      const nodeHead = document.querySelector(".node-file-head small");
      if (nodeHead && node) nodeHead.textContent = nodeLabel(nodeId);
    } else {
      const crumbs = document.querySelector(".crumbs");
      if (crumbs && node) {
        crumbs.innerHTML = '当前位置：施工方 / 项目文件上传与文件库　　当前项目：<span class="pill blue">' + escapeHtml(project.name) + '</span>　　当前反馈节点：<span class="pill red">' + escapeHtml(nodeLabel(nodeId)) + '</span>';
      }
    }

    try {
      localStorage.setItem(STORAGE_PREFIX + role, project.id);
    } catch (error) {
      // Local storage may be unavailable in some embedded previews.
    }

    const url = new URL(global.location.href);
    url.searchParams.set("projectId", project.id);
    url.searchParams.set("nodeId", String(nodeId));
    global.history.replaceState({}, "", url);
  }

  function ensureLayer() {
    let layer = document.querySelector(".project-switch-layer");
    if (layer) return layer;

    layer = document.createElement("div");
    layer.className = "project-switch-layer";
    layer.innerHTML = [
      '<div class="project-switch-backdrop" data-project-switch-close></div>',
      '<section class="project-switch-panel" role="dialog" aria-modal="true" aria-labelledby="project-switch-title">',
      '  <div class="project-switch-head">',
      '    <div><h2 id="project-switch-title">切换项目</h2><div class="sub">选择授权项目后刷新当前工作台上下文</div></div>',
      '    <button type="button" class="layer-close" data-project-switch-close>×</button>',
      '  </div>',
      '  <div class="project-switch-tools">',
      '    <input type="search" class="project-switch-search" placeholder="搜索项目名称、单位、区域" />',
      '    <span class="pill blue">项目级上下文</span>',
      '  </div>',
      '  <div class="project-switch-list"></div>',
      '</section>'
    ].join("");
    document.body.appendChild(layer);
    return layer;
  }

  function projectCard(project, role, activeId) {
    const active = project.id === activeId;
    const status = project.statuses[role];
    return [
      '<button type="button" class="project-option' + (active ? " active" : "") + '" data-project-option="' + project.id + '">',
      '  <span class="project-option-main">',
      '    <strong>' + escapeHtml(project.name) + '</strong>',
      '    <small>' + escapeHtml(project.owner) + ' · ' + escapeHtml(project.org) + ' · ' + escapeHtml(project.region) + '</small>',
      '  </span>',
      '  <span class="project-option-meta">',
      '    <span class="pill ' + statusPill(status) + '">' + escapeHtml(status) + '</span>',
      '    <span>待审 ' + project.stats.review + '</span>',
      '    <span>补正 ' + project.stats.correction + '</span>',
      '    <span>超期 ' + project.stats.overdue + '</span>',
      '    <span>' + escapeHtml(project.updatedAt) + '</span>',
      '  </span>',
      '</button>'
    ].join("");
  }

  function renderProjectList(layer, role, filter) {
    const currentId = document.querySelector("[data-project-switcher]")?.dataset.currentProject || "";
    const keyword = (filter || "").trim().toLowerCase();
    const list = layer.querySelector(".project-switch-list");
    const matched = PROJECTS.filter((project) => {
      const haystack = [project.name, project.org, project.owner, project.region, project.statuses[role]].join(" ").toLowerCase();
      return !keyword || haystack.includes(keyword);
    });
    list.innerHTML = matched.length
      ? matched.map((project) => projectCard(project, role, currentId)).join("")
      : '<div class="readonly-mask">没有匹配的授权项目。</div>';
  }

  function openSwitcher(trigger) {
    const role = trigger.dataset.role || roleFromPage();
    const layer = ensureLayer();
    renderProjectList(layer, role, "");
    layer.dataset.role = role;
    layer.classList.add("open");
    layer.querySelector(".project-switch-search").value = "";
    layer.querySelector(".project-switch-search").focus();
  }

  function closeSwitcher() {
    const layer = document.querySelector(".project-switch-layer");
    if (layer) layer.classList.remove("open");
  }

  function initialProjectId(role, trigger) {
    const url = new URL(global.location.href);
    const fromUrl = url.searchParams.get("projectId");
    if (fromUrl && projectById(fromUrl).id === fromUrl) return fromUrl;
    try {
      const stored = localStorage.getItem(STORAGE_PREFIX + role);
      if (stored && projectById(stored).id === stored) return stored;
    } catch (error) {
      // Ignore storage errors in local file previews.
    }
    return trigger.dataset.currentProject || PROJECTS[0].id;
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-project-switcher]");
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      openSwitcher(trigger);
      return;
    }

    if (event.target.closest("[data-project-switch-close]")) {
      event.preventDefault();
      event.stopPropagation();
      closeSwitcher();
      return;
    }

    const option = event.target.closest("[data-project-option]");
    if (option) {
      const role = option.closest(".project-switch-layer").dataset.role || roleFromPage();
      updateProjectContext(projectById(option.dataset.projectOption), role);
      closeSwitcher();
    }
  });

  document.addEventListener("input", (event) => {
    if (!event.target.matches(".project-switch-search")) return;
    const layer = event.target.closest(".project-switch-layer");
    renderProjectList(layer, layer.dataset.role || roleFromPage(), event.target.value);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSwitcher();
  });

  document.querySelectorAll("[data-project-switcher]").forEach((trigger) => {
    const role = trigger.dataset.role || roleFromPage();
    updateProjectContext(projectById(initialProjectId(role, trigger)), role);
  });

  global.WorkbenchProjectSwitcher = {
    projects: PROJECTS,
    updateProjectContext
  };
})(window, document);
