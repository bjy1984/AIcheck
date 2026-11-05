"""页面与交互：接口测不到的部分。mode=ui 的由 frontend/e2e/full-function.spec.ts 自动跑，
mode=manual 的靠人工按步骤点（真实设备、真实识别、打印版式这类自动化代价太高的）。
"""

from __future__ import annotations

from scripts.full_function_check.base import ui_case

ui_case(
    "UI-01",
    "登录页不预填口令",
    role="public",
    steps=["打开 /login", "看用户名、口令输入框"],
    expected="两个框都是空的；口令框是密码类型",
    priority="P0",
)
ui_case(
    "UI-02",
    "各角色登录后落到自己的工作台",
    role="all",
    steps=["分别用监检、施工方、无损、建设方、管理员登录"],
    expected="监检→/workbench/inspection，施工方→/workbench/contractor，无损→/workbench/ndt，"
    "建设方→/workbench/owner，管理员→/admin/overview；页面无报错",
    priority="P0",
)
ui_case(
    "UI-03",
    "监检工作台：项目切换与工位总览",
    role="inspection",
    steps=["监检登录", "顶部切换项目", "看工位总览的节点卡片和状态计数", "展开一个节点卡片"],
    expected="切换后数据跟着换；卡片显示节点状态和必传资料缺项；展开后能看到流程步骤",
    priority="P0",
)
ui_case(
    "UI-04",
    "节点审查页：页头状态、资料卡、逐条核对、右栏结论",
    role="inspection",
    steps=[
        "从工位总览进入节点 24",
        "看页头一行状态",
        "点开资料卡预览原件",
        "逐条核对区勾选一条",
        "右栏填结论",
    ],
    expected="页头一行显示节点状态；资料卡能预览原件；右栏结论区固定不随滚动消失；窄屏不横向溢出",
    priority="P0",
    mode="manual",
)
ui_case(
    "UI-05",
    "下结论与打回对话框的必填校验",
    role="inspection",
    steps=["不填意见直接保存结论", "打开打回对话框，不填理由直接提交"],
    expected="都提示必填，不发请求；填好后保存成功并刷新节点状态",
    priority="P0",
    mode="manual",
)
ui_case(
    "UI-06",
    "施工方工作台（含手机版）",
    role="contractor",
    steps=[
        "施工方登录（桌面和 375px 宽各看一次）",
        "看状态筛选",
        "看资料卡的 ⋯ 菜单",
        "进「待提交」上传一份 PDF",
    ],
    expected="状态筛选只显示有数量的状态；⋯ 菜单有预览/替换/删除；上传有进度，完成后出现在待提交里",
    priority="P0",
)
ui_case(
    "UI-07",
    "无损工作台：监检意见、资料清单、操作入口",
    role="ndt",
    steps=[
        "无损登录",
        "看监检意见卡片、资料清单和操作入口",
        "打开一条意见点「回复」（回复本身见 NDT-08）",
    ],
    expected="三块都在；回复对话框能打开，提交成功后自动关闭",
    priority="P0",
)
ui_case(
    "UI-08",
    "建设方首页（含手机版）",
    role="owner",
    steps=["建设方登录（375px 宽）", "看项目进度", "点一个节点打开资料抽屉", "看报告列表"],
    expected="节点资料用抽屉展示，表格在小屏改成列表；报告能打开",
    priority="P1",
)
ui_case(
    "UI-09",
    "对外角色的页面不出现「AI」字样",
    role="outside",
    steps=["施工方、无损、建设方分别登录", "检查工作台、帮助面板、消息里的文字"],
    expected="看不到「AI」「人工智能」，统一说「审核员」等",
    priority="P0",
)
ui_case(
    "UI-10",
    "意见反馈按钮只给监检和管理员",
    role="all",
    steps=["各角色登录后看右下角/账号菜单"],
    expected="监检、管理员有「意见反馈」；施工方、无损、建设方没有",
    priority="P1",
)
ui_case(
    "UI-11",
    "使用帮助面板：各角色都能打开",
    role="all",
    steps=["账号菜单点「使用帮助」（或地址带 ?help=1）", "切换几个任务看截图和编号标记"],
    expected="面板打开，内容是本角色的；截图上的编号与下面的说明一一对应",
    priority="P1",
)
ui_case(
    "UI-12",
    "帮助里的跳转按钮落到正确位置",
    role="all",
    steps=["在帮助面板点「去「…」」或「打开「…」」按钮"],
    expected="页面跳到按钮名里说的那个位置并高亮；按钮名与目标页面标题一致",
    priority="P1",
)
ui_case(
    "UI-13",
    "开始引导与首访提示",
    role="contractor",
    steps=["新账号首次进入工作台", "点「开始引导」走完全部步骤", "刷新页面"],
    expected="首访提示只出现一次；引导能前进、后退、中途退出；刷新后不再弹提示",
    priority="P2",
    mode="manual",
)
ui_case(
    "UI-14",
    "账号菜单「安装节点审计 skill」",
    role="inspection,admin",
    steps=[
        "监检打开账号菜单，点「安装节点审计 skill」",
        "点「复制」",
        "点「重新生成」",
        "施工方打开账号菜单",
    ],
    expected="弹窗显示提示词和有效期；复制成功有提示；重新生成后链接变化；施工方菜单里没有这一项",
    priority="P1",
)
ui_case(
    "UI-15",
    "消息与待办铃铛",
    role="contractor",
    steps=["监检打回一个节点后，施工方登录", "点铃铛看消息", "点开一条", "补正提交后再看待办"],
    expected="铃铛有未读数；点开后变已读；补正提交后对应待办自动关闭",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-16",
    "管理后台各页面",
    role="admin",
    steps=["管理员依次打开项目管理、组织用户、意见反馈、规则升级、审查口径、改进任务、审计日志"],
    expected="每页都能打开、有数据或空状态提示，无报错",
    priority="P1",
)
ui_case(
    "UI-17",
    "AI 助手小窗（监检）",
    role="inspection",
    steps=["打开右下角 AI 助手", "问「怎么打回补正」"],
    expected="回答引用使用教程里的步骤；不编造不存在的按钮",
    priority="P2",
    mode="manual",
)
ui_case(
    "UI-18",
    "主要页面没有控制台报错",
    role="all",
    steps=["各角色登录后打开自己的主页", "看浏览器控制台"],
    expected="没有 error 级别的日志、没有失败的接口请求（4xx/5xx）",
    priority="P1",
)
ui_case(
    "UI-19",
    "修改密码页",
    role="inspection",
    steps=["打开 /change-password", "新口令填 5 位", "新口令与旧口令相同"],
    expected="都提示不合规，不提交；合规后修改成功并跳回工作台",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-20",
    "项目邀请链接注册（/join/:token）",
    role="public",
    steps=["管理员生成项目邀请链接", "未登录打开链接填写申请", "管理员审批"],
    expected="申请提交成功；审批通过后对方能登录并看到该项目",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-21",
    "skill 网页授权（/skill-authorize）",
    role="inspection",
    steps=["本机 skill 执行 login --web，浏览器打开授权链接", "用监检账号登录并点授权"],
    expected="授权成功后回调本机，skill 拿到令牌；用别的账号登录时授权的是当前登录账号",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-22",
    "一条提示词在用户电脑上装好 skill",
    role="inspection",
    steps=[
        "把安装提示词发给电脑上的 AI 助手",
        "看它下载、核对校验值、安装、自检",
        "按提示在浏览器授权",
        "说「审计 P-xxx 节点 24」",
    ],
    expected="全程不需要手工解压配环境；校验值不对会停下；装好后能出审计报告",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-23",
    "资料原件预览（PDF、Word、Excel、图片）",
    role="inspection",
    steps=["分别打开 PDF、Word、Excel、图片资料的预览"],
    expected="都能在页面里看；Office 预览服务不可用时给出下载入口而不是白屏",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-24",
    "一键分析：进度与结果",
    role="inspection",
    steps=["工位总览点「一键分析」", "看进度", "完成后看摘要"],
    expected="进度持续更新、不会卡在排队；完成后每个节点有结果，失败的节点说明原因",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-25",
    "真实扫描件识别抽查",
    role="inspection",
    steps=["上传 3 份真实扫描件（证书、报告、图纸）", "等识别完成", "对照原件核对关键字段"],
    expected="关键字段（编号、姓名、日期、有效期）与原件一致；识别不了的页说明原因",
    priority="P1",
    mode="manual",
)
ui_case(
    "UI-26",
    "报告导出与打印版式",
    role="inspection",
    steps=["生成节点报告并导出", "打印预览"],
    expected="版式完整、分页合理、证据引用页码正确",
    priority="P2",
    mode="manual",
)
