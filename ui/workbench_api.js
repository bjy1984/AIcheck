(function (global) {
  const PROJECT_ID = "P-2026-HDCP-001";
  const DEFAULT_LATENCY = 260;

  const ENDPOINTS = {
    listAuthorizedProjects: "GET /api/workbench/projects?role={role}",
    getProjectWorkbenchContext: "GET /api/projects/{projectId}/workbench/context?role={role}",
    getWorkbenchSummary: "GET /api/projects/{projectId}/workbench/summary?role={role}",
    getProjectTree: "GET /api/projects/{projectId}/tree?role={role}",
    getNodePackage: "GET /api/projects/{projectId}/nodes/{nodeId}/package",
    createUploadSession: "POST /api/projects/{projectId}/documents/upload-session",
    bindDocumentsToNodes: "POST /api/projects/{projectId}/documents/bindings",
    saveDraft: "POST /api/projects/{projectId}/submissions/drafts",
    submitContractorBatch: "POST /api/projects/{projectId}/submissions",
    withdrawSubmissionItem: "POST /api/projects/{projectId}/submissions/{submissionId}/withdraw-items",
    submitRectification: "POST /api/projects/{projectId}/rectifications",
    uploadInspectionAttachment: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/attachments",
    mountInspectionFile: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/file-bindings",
    recheckNode: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-recheck",
    saveInspectionOpinion: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/review-opinions",
    adoptAiSuggestion: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/adopt",
    rejectAiSuggestion: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/ai-suggestions/{suggestionId}/reject",
    returnCorrection: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/actions/return-correction",
    startReportReview: "POST /api/projects/{projectId}/inspection/nodes/{nodeId}/report-review",
    getEvidenceChain: "GET /api/projects/{projectId}/inspection/nodes/{nodeId}/evidence-chain",
    getRuleVersion: "GET /api/projects/{projectId}/inspection/nodes/{nodeId}/rules/current-version"
  };

  const mockState = {
    projectId: PROJECT_ID,
    uploadSessionSeq: 1042,
    submissionSeq: 238,
    operationSeq: 9000,
    updatedAt: "2026-06-25 13:40",
    contractor: {
      batchId: "SUB-DRAFT-20260625-003",
      draftFiles: 12,
      mountedFiles: 8,
      unmountedFiles: 3,
      correctionItems: 1
    },
    inspection: {
      activeNodeId: "24",
      suggestionId: "AIS-24-20260625-01",
      reviewStatus: "待人工确认",
      evidenceLinks: 11
    }
  };

  function isLiveMode() {
    const params = new URLSearchParams(global.location ? global.location.search : "");
    return params.get("api") === "live" || global.WORKBENCH_API_MODE === "live";
  }

  function compileEndpoint(key, params) {
    let template = ENDPOINTS[key] || key;
    const methodMatch = template.match(/^(GET|POST|PUT|PATCH|DELETE)\s+/);
    const method = methodMatch ? methodMatch[1] : "GET";
    let path = template.replace(/^(GET|POST|PUT|PATCH|DELETE)\s+/, "");
    const merged = Object.assign({ projectId: PROJECT_ID }, params || {});
    Object.keys(merged).forEach((name) => {
      path = path.replace(new RegExp("\\{" + name + "\\}", "g"), encodeURIComponent(merged[name]));
    });
    return { method, path, descriptor: method + " " + path };
  }

  function nextOperation(prefix) {
    mockState.operationSeq += 1;
    return prefix + "-" + mockState.operationSeq;
  }

  function delay(result) {
    return new Promise((resolve) => {
      global.setTimeout(() => resolve(result), DEFAULT_LATENCY);
    });
  }

  function mockResponse(key, params, payload) {
    const endpoint = compileEndpoint(key, params);
    const base = {
      ok: true,
      mock: true,
      endpoint: endpoint.descriptor,
      projectId: PROJECT_ID,
      received: payload || null,
      operationId: nextOperation("MOCK")
    };

    switch (key) {
      case "createUploadSession":
        mockState.uploadSessionSeq += 1;
        mockState.contractor.draftFiles += (payload && payload.files ? payload.files.length : 1);
        return delay(Object.assign(base, {
          uploadSessionId: "UP-" + mockState.uploadSessionSeq,
          files: payload && payload.files ? payload.files : ["待选择文件"],
          message: "上传会话已创建，文件进入项目文件库草稿区。"
        }));
      case "bindDocumentsToNodes":
      case "mountInspectionFile":
        mockState.contractor.mountedFiles += 1;
        if (mockState.contractor.unmountedFiles > 0) mockState.contractor.unmountedFiles -= 1;
        return delay(Object.assign(base, { message: "节点挂载关系已保存。" }));
      case "saveDraft":
        return delay(Object.assign(base, { draftId: mockState.contractor.batchId, message: "草稿已保存。" }));
      case "submitContractorBatch":
        mockState.submissionSeq += 1;
        mockState.contractor.unmountedFiles = Math.max(0, mockState.contractor.unmountedFiles - 1);
        return delay(Object.assign(base, {
          submissionId: "SUB-20260625-" + mockState.submissionSeq,
          nextStatus: "AI 预审中",
          message: "文件与挂载关系已提交，等待 AI 预审和监检复核。"
        }));
      case "withdrawSubmissionItem":
        return delay(Object.assign(base, { message: "未提交文件已撤回，已提交文件仅保留撤回申请入口。" }));
      case "submitRectification":
        mockState.contractor.correctionItems = Math.max(0, mockState.contractor.correctionItems - 1);
        return delay(Object.assign(base, {
          rectificationId: "REC-20260625-016",
          nextStatus: "待复审",
          message: "补正反馈已提交，节点进入待复审。"
        }));
      case "recheckNode":
        return delay(Object.assign(base, {
          runId: "AIRUN-24-20260625-02",
          evidenceLinks: mockState.inspection.evidenceLinks + 1,
          message: "重新核验任务已进入队列，当前原型返回模拟完成结果。"
        }));
      case "saveInspectionOpinion":
        mockState.inspection.reviewStatus = "已保存意见";
        return delay(Object.assign(base, {
          opinionId: "OPN-24-20260625-01",
          result: payload && payload.result,
          opinion: payload && payload.opinion,
          message: "审查意见已保存，等待确认或退回。"
        }));
      case "adoptAiSuggestion":
        mockState.inspection.reviewStatus = "已采纳 AI 建议";
        return delay(Object.assign(base, {
          draftResult: payload && payload.result,
          draftOpinion: payload && payload.opinion,
          message: "AI 建议已采纳为审查意见草稿，最终结论仍需监检人员确认。"
        }));
      case "rejectAiSuggestion":
        mockState.inspection.reviewStatus = "已驳回 AI 建议";
        return delay(Object.assign(base, { message: "AI 建议已驳回，请补充人工审查意见。" }));
      case "returnCorrection":
        mockState.inspection.reviewStatus = "已退回补正";
        return delay(Object.assign(base, {
          correctionNoticeId: "RCN-24-20260625-01",
          nextStatus: "退回补正中",
          message: "退回补正通知已生成。"
        }));
      case "startReportReview":
        return delay(Object.assign(base, {
          reportDraftId: "RPT-DRAFT-20260625-01",
          nextStatus: "报告生成/复核中",
          message: "报告草稿已生成并进入复核队列。"
        }));
      case "getEvidenceChain":
        return delay(Object.assign(base, {
          links: [
            "焊工资格证-王建国.pdf / 第1页 / 证书编号",
            "焊工名册.xlsx / 第4行 / 身份证尾号",
            "焊接工艺卡.docx / 第1页 / GTAW+SMAW",
            "资格网站查询截图.png / 区域A / 证书状态"
          ]
        }));
      case "getRuleVersion":
        return delay(Object.assign(base, {
          ruleVersion: "Welder-Qualification-B-v2.1",
          promptVersion: "24-焊工资格-v1.5",
          message: "当前节点规则版本已返回。"
        }));
      case "listAuthorizedProjects":
        return delay(Object.assign(base, { message: "授权项目列表已返回。" }));
      case "getProjectWorkbenchContext":
        return delay(Object.assign(base, { message: "项目工作台上下文已返回。" }));
      default:
        return delay(Object.assign(base, { message: "预留接口已命中 mock 适配层。" }));
    }
  }

  async function liveRequest(key, params, payload) {
    const endpoint = compileEndpoint(key, params);
    const init = {
      method: endpoint.method,
      headers: { "Content-Type": "application/json" }
    };
    if (!/GET|HEAD/.test(endpoint.method)) init.body = JSON.stringify(payload || {});
    const response = await fetch((global.WORKBENCH_API_BASE || "") + endpoint.path, init);
    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || response.statusText);
    }
    return response.json();
  }

  function request(key, params, payload) {
    if (isLiveMode()) return liveRequest(key, params, payload);
    return mockResponse(key, params, payload);
  }

  global.WorkbenchApi = {
    PROJECT_ID,
    ENDPOINTS,
    mode: isLiveMode() ? "live" : "mock",
    compileEndpoint,
    listReservedEndpoints() {
      return Object.keys(ENDPOINTS).map((key) => Object.assign({ key }, compileEndpoint(key)));
    },
    listAuthorizedProjects(role) {
      return request("listAuthorizedProjects", { role });
    },
    getProjectWorkbenchContext(projectId, role) {
      return request("getProjectWorkbenchContext", { projectId, role });
    },
    getWorkbenchSummary(role) {
      return request("getWorkbenchSummary", { role });
    },
    getProjectTree(role) {
      return request("getProjectTree", { role });
    },
    getNodePackage(nodeId) {
      return request("getNodePackage", { nodeId });
    },
    createUploadSession(payload) {
      return request("createUploadSession", {}, payload);
    },
    bindDocumentsToNodes(payload) {
      return request("bindDocumentsToNodes", {}, payload);
    },
    saveDraft(payload) {
      return request("saveDraft", {}, payload);
    },
    submitContractorBatch(payload) {
      return request("submitContractorBatch", {}, payload);
    },
    withdrawSubmissionItem(submissionId, payload) {
      return request("withdrawSubmissionItem", { submissionId: submissionId || "draft" }, payload);
    },
    submitRectification(payload) {
      return request("submitRectification", {}, payload);
    },
    uploadInspectionAttachment(nodeId, payload) {
      return request("uploadInspectionAttachment", { nodeId }, payload);
    },
    mountInspectionFile(nodeId, payload) {
      return request("mountInspectionFile", { nodeId }, payload);
    },
    recheckNode(nodeId, payload) {
      return request("recheckNode", { nodeId }, payload);
    },
    saveInspectionOpinion(nodeId, payload) {
      return request("saveInspectionOpinion", { nodeId }, payload);
    },
    adoptAiSuggestion(nodeId, suggestionId, payload) {
      return request("adoptAiSuggestion", { nodeId, suggestionId }, payload);
    },
    rejectAiSuggestion(nodeId, suggestionId, payload) {
      return request("rejectAiSuggestion", { nodeId, suggestionId }, payload);
    },
    returnCorrection(nodeId, payload) {
      return request("returnCorrection", { nodeId }, payload);
    },
    startReportReview(nodeId, payload) {
      return request("startReportReview", { nodeId }, payload);
    },
    getEvidenceChain(nodeId) {
      return request("getEvidenceChain", { nodeId });
    },
    getRuleVersion(nodeId) {
      return request("getRuleVersion", { nodeId });
    }
  };
})(window);
