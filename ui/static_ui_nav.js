(function () {
  const PAGE = "./static_ui_interactions.html";

  function clean(text) {
    return (text || "").replace(/\s+/g, " ").trim();
  }

  function roleOf(el) {
    const workspace = el.closest(".workspace");
    if (workspace && workspace.id) return workspace.id;

    const title = document.title || "";
    const path = location.pathname || "";
    if (/contractor|施工方/.test(path + title)) return "contractor";
    if (/inspection|监检/.test(path + title)) return "inspection";
    if (/ndt|无损检测/.test(path + title)) return "ndt";
    if (/owner|建设方/.test(path + title)) return "owner";
    if (/admin|管理后台/.test(path + title)) return "admin";
    return "common";
  }

  function adminTreeTarget(label) {
    if (/权限矩阵|节点与角色权限/.test(label)) return "admin-permission-matrix";
    if (/项目列表|项目台账|项目管理与基础配置/.test(label)) return "project-list";
    if (/项目详情/.test(label)) return "project-detail";
    if (/项目立项|立项向导|新建项目/.test(label)) return "project-create-wizard";
    if (/组织用户|用户中心|组织机构|用户账号/.test(label)) return "org-users";
    if (/角色权限|菜单权限|接口权限|审核动作/.test(label)) return "role-permission";
    if (/项目成员授权|成员授权/.test(label)) return "project-member-auth";
    if (/流程状态机|流程管理/.test(label)) return "workflow-state-machine";
    if (/待办规则/.test(label)) return "todo-rule-config";
    if (/流程实例/.test(label)) return "workflow-instance-detail";
    if (/项目审核节点维护|项目文件树节点维护/.test(label)) return "admin-node-tree";
    if (/AI 业务审查规则模板|规则模板/.test(label)) return "admin-rule-template";
    if (/外部核验工具源/.test(label)) return "admin-tool-source";
    if (/证据字段映射/.test(label)) return "admin-field-mapping";
    if (/角色单位人员维护|角色维护|单位管理|人员维护|人员与角色绑定/.test(label)) return "admin-people-role";
    if (/操作日志|审计/.test(label)) return "audit-log";
    return "admin-node-tree";
  }

  function treeTarget(label, role) {
    if (role === "admin") return adminTreeTarget(label);
    if (/报告归档|归档资料/.test(label)) return "archive-browser";
    if (/项目总览|项目概况/.test(label)) return "owner-node-summary";
    if (/无损检测/.test(label) && role === "ndt") return "ndt-node-detail";
    return "node-detail";
  }

  function routeFor(el) {
    const role = roleOf(el);
    const label = clean(el.textContent) || clean(el.getAttribute("title"));

    if (!label) return "";

    if (el.classList.contains("global-search") || el.classList.contains("search")) return "global-search";
    if (el.classList.contains("upload-box") || el.classList.contains("upload-zone")) {
      return role === "ndt" ? "ndt-upload-report" : "contractor-upload";
    }
    if (el.classList.contains("section-tools")) {
      if (/反馈/.test(label)) return "feedback-detail";
      if (/只读|ⓘ|i/.test(label)) return "readonly-scope";
      if (/⚙/.test(label)) return role === "admin" ? "admin-permission-matrix" : "filter-settings";
      if (/↻/.test(label)) return "refresh-state";
    }
    if (el.matches(".tree-node, .tree-group, .tree-root, .tree-folder")) return treeTarget(label, role);

    if (el.closest(".top-actions")) {
      if (/待办|提醒|配置待办/.test(label)) return "todo-center";
      if (/消息/.test(label)) return "message-center";
      if (/审计/.test(label)) return "audit-log";
      if (/施工方|监检员|无损检测|建设方|系统管理员|张工|李工|王工|陈经理|周工/.test(label)) return "user-menu";
    }

    if (/项目列表|项目台账/.test(label)) return "project-list";
    if (/项目详情|打开项目详情/.test(label)) return "project-detail";
    if (/项目立项|立项向导|新建项目|创建项目/.test(label)) return "project-create-wizard";
    if (/组织用户|用户账号|组织机构/.test(label)) return "org-users";
    if (/角色权限配置|菜单权限|接口权限|审核动作权限/.test(label)) return "role-permission";
    if (/项目成员授权|成员授权/.test(label)) return "project-member-auth";
    if (/流程状态机/.test(label)) return "workflow-state-machine";
    if (/待办规则/.test(label)) return "todo-rule-config";
    if (/流程实例详情|查看流程实例/.test(label)) return "workflow-instance-detail";

    if (/新增规则模板|复制模板|编辑模板/.test(label)) return "admin-rule-template";
    if (/配置字段/.test(label)) return "admin-field-mapping";
    if (/查看版本/.test(label)) return "admin-version";
    if (/导出配置/.test(label)) return "admin-export";
    if (/导出状态摘要|导出清单/.test(label)) return "export-center";
    if (/批量归类/.test(label)) return "batch-classify";
    if (/刷新状态|↻/.test(label)) return "refresh-state";
    if (/≡|筛选|只看未挂载|只看需补正/.test(label)) return "filter-settings";
    if (/⌕|定位$/.test(label)) return "evidence-locator";
    if (/只读|ⓘ|^i$/.test(label)) return "readonly-scope";

    if (/批量上传文件|选择文件|上传补正附件/.test(label)) return "contractor-upload";
    if (/选择挂载节点|按节点挂载资料|挂载文件/.test(label)) {
      return role === "inspection" ? "inspection-mount-file" : "contractor-mount-node";
    }
    if (/^提交$|提交本批文件及挂载关系|提交选中文件及挂载关系|提交本节点文件包|提交选中文件|提交补正反馈/.test(label)) return "contractor-submit";
    if (/保存草稿/.test(label)) return "draft-save";
    if (/撤回未提交文件|撤回未提交/.test(label)) return "withdraw-submit";
    if (/查看历史版本/.test(label)) return "file-history";
    if (/补正反馈/.test(label)) return "feedback-correction";
    if (/查看\/替换|查看反馈|关联意见|查看$/.test(label)) return /反馈|意见/.test(label) ? "feedback-detail" : "file-detail";

    if (/重新核验|重新推理/.test(label)) return "ai-recheck";
    if (/查看规则版本/.test(label)) return "rule-version";
    if (/复制业务结论|复制结论/.test(label)) return "copy-conclusion";
    if (/上传监检资料/.test(label)) return "inspection-upload";
    if (/保存审查意见|保存意见/.test(label)) return "inspection-opinion";
    if (/采纳 AI 建议|采纳结果/.test(label)) return "ai-adopt";
    if (/驳回 AI 建议|驳回结果/.test(label)) return "ai-reject";
    if (/退回补正/.test(label)) return "return-correction";
    if (/报告生成\s*\/\s*复核|报告生成\/复核/.test(label)) return "report-review";
    if (/定位证据|定位反馈|定位底片|定位意见/.test(label)) return "evidence-locator";
    if (/查看日期比对/.test(label)) return "date-compare";
    if (/查看条款|标准依据/.test(label)) return "standard-reference";
    if (/查看证据链/.test(label)) return "evidence-chain";
    if (/放大|缩小/.test(label)) return "preview-zoom";
    if (/下载/.test(label)) return "download-center";

    if (/新增底片编号/.test(label)) return "ndt-film-add";
    if (/批量导入记录|批量导入/.test(label)) return "ndt-import";
    if (/上传检测报告/.test(label)) return "ndt-upload-report";
    if (/提交检测资料/.test(label)) return "ndt-submit";
    if (/查看监检意见/.test(label)) return "inspection-feedback";

    if (/预览报告/.test(label)) return "owner-report-preview";
    if (/浏览归档资料/.test(label)) return "archive-browser";
    if (/查看节点资料摘要/.test(label)) return "owner-node-summary";

    if (/节点文件/.test(label)) return "tab-node-files";
    if (/资料预览/.test(label)) return "tab-preview";
    if (/OCR 识别/.test(label)) return "tab-ocr";
    if (/AI 审查/.test(label)) return "tab-ai-review";
    if (/审查记录/.test(label)) return "tab-review-log";

    return "static-action-fallback";
  }

  function markInteractive() {
    const selector = [
      "button:not(.role-tab)",
      "a:not([href])",
      ".global-search",
      ".search",
      ".top-actions > span",
      ".top-actions > div",
      ".tree-node",
      ".tree-group",
      ".tree-root",
      ".tree-folder",
      ".section-tools",
      ".upload-box",
      ".upload-zone"
    ].join(",");

    document.querySelectorAll(selector).forEach((el) => {
      el.style.cursor = "pointer";
      if (!el.getAttribute("title")) {
        const target = routeFor(el);
        if (target) el.setAttribute("title", "打开静态页面：" + target);
      }
    });
  }

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.target.closest(".workbench-layer, .project-switch-layer, [data-project-switcher]")) return;

    const trigger = event.target.closest([
      "button:not(.role-tab)",
      "a:not([href])",
      ".global-search",
      ".search",
      ".top-actions > span",
      ".top-actions > div",
      ".tree-node",
      ".tree-group",
      ".tree-root",
      ".tree-folder",
      ".section-tools",
      ".upload-box",
      ".upload-zone"
    ].join(","));

    if (!trigger) return;
    const target = routeFor(trigger);
    if (!target) return;

    event.preventDefault();
    window.location.href = PAGE + "#" + target;
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", markInteractive);
  } else {
    markInteractive();
  }
})();
