(function (global, document) {
  const DEFAULT_PROJECT_NAME = "华东成品油管道改造工程";

  const GROUPS = [
    {
      name: "受检单位资质",
      nodes: [
        [1, "设计单位许可资质", "C"],
        [2, "施工单位许可资质", "C"],
        [3, "无损检测机构核准资质", "C"]
      ]
    },
    {
      name: "设计文件",
      nodes: [
        [4, "设计文件的批准程序", "C"],
        [5, "施工图审查手续", "C"],
        [6, "强度计算书、管道应力分析计算书的审批手续", "C"],
        [7, "设计变更的书面批准文件", "C"],
        [8, "设计采用的安全技术规范以及相关标准、压力管道元件的材料标准的版本", "C"],
        [9, "设计文件上注明的无损检测、防腐、耐压试验和泄漏试验要求", "C"],
        [10, "采用其他标准时，设计文件或工程规定中应包括符合《工业管道安全技术规程》基本安全的符合性申明及比照表", "需确认"]
      ]
    },
    { name: "施工组织设计", nodes: [[11, "施工组织设计", "C"]] },
    {
      name: "材料",
      nodes: [
        [12, "压力管道元件及安全附件制造单位的许可资质", "C"],
        [13, "需制造监检或有型式试验要求的压力管道元件的监检证书、型式试验报告", "C"],
        [14, "不需制造许可、监检、型式试验的管道组成件的出厂检验报告，必要时进行现场抽查复验", "C/B"],
        [15, "境外制造的压力管道元件、安全附件的型式试验证书及其制造单位的制造许可证资质", "C"],
        [16, "压力管道元件以及安全附件产品质量证明文件", "C"],
        [17, "压力管道元件以及安全附件产品验收的见证资料、抽样复验", "C"],
        [18, "材料复验报告、无损检测报告", "C"],
        [19, "使用境外牌号材料制造的压力管道元件以及安全附件，验证性复验结果", "C"],
        [20, "新材料制造的压力管道元件以及安全附件的型式试验报告、技术评审、批准手续", "C"],
        [21, "材料标志移植", "B"],
        [22, "材料代用", "C"]
      ]
    },
    { name: "阀门", nodes: [[23, "阀门的施工资料和耐压试验记录（报告）", "C"]] },
    {
      name: "焊接（粘接）",
      nodes: [
        [24, "焊工资格证及持证合格项目", "B"],
        [25, "焊接（粘接）工艺文件", "C"],
        [26, "焊接材料质量证明文件", "C"],
        [27, "焊接材料的验收、保管、发放、使用和回收的管理", "B"],
        [28, "管道组对", "C"],
        [29, "施焊参数、施焊记录、焊缝标识", "B"],
        [30, "焊接接头外观质量", "B"],
        [31, "焊缝返修", "C"]
      ]
    },
    {
      name: "热处理",
      nodes: [
        [32, "焊接接头焊后热处理工艺文件", "C"],
        [33, "热处理设备用测温记录仪表", "C"],
        [34, "热处理记录、报告曲线、硬度检测报告", "C"]
      ]
    },
    {
      name: "无损检测",
      nodes: [
        [35, "无损检测机构施工现场质量保证体系的实施", "B"],
        [36, "无损检测方案", "C"],
        [37, "检测过程中发现问题的处理", "C"],
        [38, "无损检测人员资格证、执业注册证及持证合格项目", "B"],
        [39, "无损检测工艺文件", "C"],
        [40, "无损检测记录、报告", "C"],
        [41, "射线检测底片抽查", "B"],
        [42, "射线检测现场抽查", "B"]
      ]
    },
    {
      name: "防腐、保温",
      nodes: [
        [43, "防腐及保温材料质量证明文件", "C"],
        [44, "防腐、补口、补伤及保温", "C"],
        [45, "防腐层电火花检测", "C"],
        [46, "牺牲阳极、外加电流阴极保护、杂散电流排流装置", "C"],
        [47, "静电接地", "C"]
      ]
    },
    {
      name: "穿跨越工程",
      nodes: [
        [48, "穿跨越工程的管道结构、焊缝布置", "C"],
        [49, "穿跨越工程施工", "C"],
        [50, "套管防腐绝缘", "C"],
        [51, "绝缘支撑", "C"]
      ]
    },
    { name: "管道现场制作（预制）", nodes: [[52, "管道现场制作（预制）", "B"]] },
    {
      name: "管道安装",
      nodes: [
        [53, "管道布管与连接方式、穿跨越", "C/B"],
        [54, "补偿装置", "C/B"],
        [55, "支撑件", "C/B"]
      ]
    },
    {
      name: "安全附件",
      nodes: [
        [56, "安全阀、爆破片和紧急切断阀的安装位置、规格和型号", "B"],
        [57, "安全阀校验报告", "C"],
        [58, "紧急切断阀性能测试报告", "C"]
      ]
    },
    {
      name: "耐压试验",
      nodes: [
        [59, "耐压试验方案", "A"],
        [60, "试验用压力表、试验介质、介质温度、环境温度", "A"],
        [61, "耐压试验压力、保压时间及结果", "A"],
        [62, "耐压试验记录（报告）", "A"]
      ]
    },
    {
      name: "耐压试验免除或替代",
      nodes: [
        [63, "管道系统的柔性(应力)分析", "A"],
        [64, "现场检查替代性试验的过程", "A"],
        [65, "无损检测报告和底片", "A"]
      ]
    },
    {
      name: "泄漏试验",
      nodes: [
        [66, "试验用压力表、试验介质、介质温度、环境温度、试验压力", "B"],
        [67, "泄漏试验方法和试验报告", "C"]
      ]
    },
    { name: "吹扫、清洗", nodes: [[68, "吹扫、清洗", "C"]] },
    { name: "施工单位质量保证体系实施状况的评价", nodes: [[69, "施工单位质量保证体系实施状况的评价", "需确认"]] }
  ];

  const GROUP_STATUS = {
    inspection: {
      "材料": [{ text: "1补正", color: "red" }],
      "焊接（粘接）": [{ text: "待审查", color: "orange" }]
    },
    contractor: {
      "材料": [{ text: "3反馈", color: "orange" }],
      "受检单位资质": [{ text: "只读", color: "blue" }],
      "设计文件": [{ text: "只读", color: "blue" }],
      "焊接（粘接）": [{ text: "只读", color: "blue" }],
      "无损检测": [{ text: "只读", color: "blue" }],
      "耐压试验": [{ text: "只读", color: "blue" }]
    }
  };

  const NODE_STATUS = {
    inspection: {
      16: [{ text: "C类", color: "blue" }, { text: "1补正", color: "red" }],
      24: [{ text: "B类", color: "blue" }, { text: "待确认", color: "orange" }],
      25: [{ text: "C类", color: "blue" }, { text: "6文件" }],
      26: [{ text: "C类", color: "blue" }, { text: "8文件" }],
      29: [{ text: "B类", color: "blue" }, { text: "27文件" }]
    },
    contractor: {
      16: [{ text: "需补正", color: "red" }],
      17: [{ text: "3/4" }],
      18: [{ text: "待挂载", color: "orange" }],
      21: [{ text: "B类", color: "blue" }, { text: "5文件" }],
      25: [{ text: "待审查", color: "orange" }],
      41: [{ text: "只读", color: "blue" }]
    }
  };

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function badgeColor(text, fallback) {
    if (fallback) return fallback;
    if (/需确认|待/.test(text)) return "orange";
    if (/补正/.test(text)) return "red";
    if (/通过|满足|已/.test(text)) return "green";
    if (/[ABC]类|C\/B类/.test(text)) return "blue";
    return "";
  }

  function renderBadges(items) {
    return items.map((item) => {
      const text = typeof item === "string" ? item : item.text;
      const color = badgeColor(text, typeof item === "string" ? "" : item.color);
      return color
        ? '<span class="pill ' + color + '">' + escapeHtml(text) + "</span>"
        : escapeHtml(text);
    }).join(" ");
  }

  function nodeBadges(role, id, type) {
    if (NODE_STATUS[role] && NODE_STATUS[role][id]) return NODE_STATUS[role][id];
    return [{ text: type === "需确认" ? "需确认" : type + "类", color: type === "需确认" ? "orange" : "blue" }];
  }

  function renderTree(container) {
    const role = container.dataset.role || "common";
    const activeNode = String(container.dataset.activeNode || "");
    const projectName = container.dataset.projectName || DEFAULT_PROJECT_NAME;
    let html = '<div class="tree-root" data-tree-root><span>⌄</span><span class="tree-label">' + escapeHtml(projectName) + "</span><span></span></div>";

    GROUPS.forEach((group, index) => {
      const groupId = "tree-group-" + index;
      const statuses = GROUP_STATUS[role] && GROUP_STATUS[role][group.name] ? GROUP_STATUS[role][group.name] : [];
      html += '<div class="tree-group collapsed" data-tree-toggle="' + groupId + '" aria-expanded="false" title="展开/收起 ' + escapeHtml(group.name) + '"><span class="tree-caret">›</span><span>' + escapeHtml(group.name) + "</span><span>" + group.nodes.length + "节点";
      if (statuses.length) html += " " + renderBadges(statuses);
      html += "</span></div>";

      group.nodes.forEach(([id, name, type]) => {
        const classes = ["tree-node", "tree-node-collapsed"];
        if (String(id) === activeNode) classes.push("active");
        if (role === "contractor" && id === 18) classes.push("warn");
        html += '<div class="' + classes.join(" ") + '" data-node-id="' + id + '" data-parent-group="' + groupId + '" hidden><span>' + id + '</span><span class="tree-label">' + escapeHtml(name) + "</span><span>" + renderBadges(nodeBadges(role, id, type)) + "</span></div>";
      });
    });

    container.innerHTML = html;
  }

  function setGroupExpanded(group, expanded) {
    const tree = group.closest("[data-project-tree]");
    if (!tree) return;
    const groupId = group.dataset.treeToggle;
    group.classList.toggle("collapsed", !expanded);
    group.classList.toggle("expanded", expanded);
    group.setAttribute("aria-expanded", expanded ? "true" : "false");
    const caret = group.querySelector(".tree-caret");
    if (caret) caret.textContent = expanded ? "⌄" : "›";
    tree.querySelectorAll('[data-parent-group="' + groupId + '"]').forEach((node) => {
      node.hidden = !expanded;
      node.classList.toggle("tree-node-collapsed", !expanded);
    });
  }

  document.addEventListener("click", (event) => {
    const group = event.target.closest("[data-tree-toggle]");
    if (!group) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    setGroupExpanded(group, group.getAttribute("aria-expanded") !== "true");
  }, true);

  function renderAll() {
    document.querySelectorAll("[data-project-tree]").forEach(renderTree);
  }

  function findNode(id) {
    const wanted = Number(id);
    for (const group of GROUPS) {
      for (const node of group.nodes) {
        if (node[0] === wanted) {
          return { id: node[0], name: node[1], type: node[2], group: group.name };
        }
      }
    }
    return null;
  }

  global.WorkbenchProjectTree = {
    groups: GROUPS,
    renderTree,
    renderAll,
    findNode
  };

  renderAll();
})(window, document);
