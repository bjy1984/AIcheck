/** 监检和管理员的使用帮助（内部角色，可以提「AI」）。 */
import { ACCOUNT_SPOT, ACCOUNT_TASK, SWITCH_PROJECT_TASK } from './guideCommon'
import type { RoleGuide } from './guideTypes'

const shot = (name: string) => new URL(`./images/${name}.jpg`, import.meta.url).href

/** 2026-11-11 起：不用先建单位和账号，建项目后发邀请链接，各方自己申请、负责人审核 */
const REVIEW_JOIN_STEPS = [
  '打开「邀请成员」，下面列着提交上来的申请：姓名、单位、申请的角色。',
  '点「通过」：先核对单位名，有简称或错字就当场改；系统里没有这个单位会自动新建。',
  '单位名和项目已登记的不一样时会让你选：同一家公司选「并入」，另一家公司选「算作新单位」（两家资料互相看不到）。',
  '不认识的人点「拒绝」并写原因，对方在链接里能看到原因、改了再交。'
]

/** 2026-11-12 起：施工、无损、建设单位成员忘了密码，负责人在「邀请成员」里就能重置 */
const RESET_MEMBER_PASSWORD_STEPS = [
  '打开「邀请成员」，拉到下面「已加入的成员」。',
  '找到忘了密码的人，点「重置密码」并确认：对方原来的密码马上失效，已登录的设备会被退出。',
  '把弹出的账号和临时密码告诉对方（可以点「复制发给对方」），窗口关掉后临时密码不再显示。',
  '对方用临时密码登录后，系统会要求改成自己的密码。监检人员、管理员、其他项目的负责人不能在这里重置，请找系统管理员。'
]

const NEED_NODE =
  '这一块在节点页里：先在项目总览或左边项目树里点一个节点，再回到使用帮助点这个按钮。'

export const INSPECTION_GUIDE: RoleGuide = {
  role: 'inspection',
  roleLabel: '监检人员',
  intro:
    '先在「项目总览」看哪些节点要处理，再进节点核对资料、下结论；资料不全就退回补正。AI 只给建议，结论由你定。',
  tour: [
    {
      target: 'topbar-project',
      hint: '当前项目，点名字可以切换项目；旁边的标签是项目所处的阶段。'
    },
    {
      target: 'inspection-tree',
      hint: '左边是本项目全部审核节点，按分组展开；点一个节点进去办理，点顶上「项目总览」回到总览。'
    },
    {
      target: 'inspection-overview',
      hint: '项目总览列出全部节点，按未通过、证据不足、需人工确认、通过、未开始审核分组。点一行展开看资料和流程，右边的按钮直接进节点。',
      emptyHint: '这一块在「项目总览」里：点左边项目树顶上的「项目总览」。'
    },
    {
      target: 'inspection-view-tabs',
      hint: '「完整工作台」逐个节点办理；「重要节点审查」先选文件、再挑重点节点做专项审查。'
    },
    {
      target: 'inspection-auto-review',
      hint: '「自动审查」：资料识别并挂载后自动跑审查，也可以每天定时扫描补漏。'
    },
    { target: 'inspection-analysis', hint: '「一键分析」对整个工程的全部适用节点发起 AI 分析。' },
    {
      target: 'inspection-audit-tasks',
      hint: '「审计任务」看每个节点最近一次审查走到哪了：审查中、排队中（前面还有几个）、要你确认或重新发起的；点一行直接进那个节点。'
    },
    { target: 'topbar-messages', hint: '资料提交、补正反馈等提醒都在「待办消息」里。' },
    {
      target: 'inspection-assistant',
      hint: '右下角「AI审查」是助手：问节点要什么资料、让它找证据，也能问系统怎么用。'
    },
    {
      target: 'inspection-invite',
      hint: '项目负责人才有「邀请成员」：把链接发给施工、无损、建设单位，他们自己申请，你在这里审核。',
      emptyHint: '「邀请成员」只有项目负责人看得到。要邀请人请找项目负责人或管理员。'
    },
    ACCOUNT_SPOT
  ],
  tasks: [
    {
      id: 'overview',
      title: '看项目总览',
      summary: '先看哪些节点要处理。',
      steps: [
        '最上面是全部节点的统计：未通过、证据不足、需人工确认、通过、未开始审核。',
        '下面按这几组列出全部节点，要处理的排在前面。',
        '点一行在原地展开：必传资料齐不齐、处理流程到哪一步；点「进入节点」去办理。',
        '每行右边的按钮直接进节点：「写监检意见」「查看原因」「去确认」「开始审核」。'
      ],
      image: {
        src: shot('inspection-overview'),
        alt: '监检项目总览：节点统计和全部节点列表',
        device: 'desktop',
        markers: [
          { n: 1, x: 33.5, y: 35.5 },
          { n: 2, x: 38, y: 46 },
          { n: 3, x: 48, y: 52.6 },
          { n: 4, x: 90, y: 52.6 }
        ]
      },
      jump: {
        label: '去「项目总览」',
        target: 'inspection-overview',
        hint: '看全部节点，点一行展开。',
        emptyHint: '这一块在「项目总览」里：点左边项目树顶上的「项目总览」。'
      }
    },
    {
      id: 'materials',
      title: '核对节点资料',
      summary: '这个节点要的资料齐不齐。',
      steps: [
        '进入节点后看「资料」：标「缺」的是还没有的，右上角是必传完成数。',
        '点「挂接资料」把文件库里已有的文件挂到这一项；「资料明细与挂接」看全部。',
        '缺的资料点「通知补正」，把缺项写进补正要求退回施工方。'
      ],
      image: {
        src: shot('inspection-node'),
        alt: '节点页：资料、逐条核对、审查结论',
        device: 'desktop',
        markers: [
          { n: 1, x: 35, y: 23.4 },
          { n: 2, x: 61.1, y: 30 },
          { n: 3, x: 66, y: 36.2 }
        ]
      },
      jump: {
        label: '去节点的「资料」',
        target: 'inspection-node-materials',
        hint: '本节点要的资料在这里。',
        emptyHint: NEED_NODE
      }
    },
    {
      id: 'checks',
      title: '看逐条核对',
      summary: 'AI 对每个审查点的核对结果，红的要你处理。',
      steps: [
        '「逐条核对」列出「AI：有问题」和「AI：请你确认」的审查点；通过的、证据不足的折叠在下面。',
        '点一条展开看依据和证据；要退回就点「据此退回补正」。',
        'AI 还没审、或资料更新了，点「发起节点复核」重新审一遍。'
      ],
      image: {
        src: shot('inspection-node'),
        alt: '节点页的逐条核对',
        device: 'desktop',
        markers: [
          { n: 1, x: 35, y: 65.7 },
          { n: 3, x: 50.1, y: 78.6 }
        ]
      },
      jump: {
        label: '去「逐条核对」',
        target: 'inspection-node-checks',
        hint: 'AI 的逐条核对在这里。',
        emptyHint: NEED_NODE
      }
    },
    {
      id: 'decision',
      title: '下审查结论',
      summary: '结论由你定，保存后才算数。',
      steps: [
        '在右边「审查结论」选：满足要求、需补正、证据不足、不适用。',
        '勾选「引用证据」，在「审查意见」里写判断和依据。',
        '点「保存结论」；选「需补正」时按钮变成「保存并退回补正」，意见会一起发给施工方。',
        '必传资料还没有已确认证据时，不能选「满足要求」。'
      ],
      image: {
        src: shot('inspection-node'),
        alt: '节点页右边的审查结论',
        device: 'desktop',
        markers: [
          { n: 1, x: 81.5, y: 41.7 },
          { n: 2, x: 84.6, y: 59.6 },
          { n: 3, x: 84.6, y: 71.9 }
        ]
      },
      jump: {
        label: '去「审查结论」',
        target: 'inspection-node-decision',
        hint: '结论在右边这一栏。',
        emptyHint: NEED_NODE
      }
    },
    {
      id: 'upload',
      title: '上传监检资料、查文件库',
      summary: '监检自己的记录，和本项目全部文件。',
      steps: [
        '在节点页右上角点「上传监检资料」，上传监检现场记录等。',
        '点「文件库」看本项目全部文件，可以挂接到节点。'
      ],
      image: {
        src: shot('inspection-node'),
        alt: '节点页右上角的上传监检资料和文件库',
        device: 'desktop',
        markers: [
          { n: 1, x: 87, y: 12.1 },
          { n: 2, x: 95.5, y: 12.1 }
        ]
      },
      jump: {
        label: '去「上传监检资料」',
        target: 'inspection-upload',
        hint: '上传监检自己的资料点这里。',
        emptyHint: '先进入一个节点，右上角才有「上传监检资料」。'
      }
    },
    {
      id: 'report',
      title: '生成报告、签发归档',
      summary: '结论保存后，在节点里出报告。',
      steps: [
        '节点页底部点「处理流程」，展开七步：资料提交 → OCR 抽取 → 证据确认 → AI 复核 → 人工结论 → 报告复核 → 签发归档。',
        '点「报告复核」，选生成范围后点「生成报告草稿」；要先保存审查结论才能生成。',
        '点「签发归档」签发报告并归档，建设方就能在他们的页面下载。'
      ]
    },
    {
      id: 'bulk',
      title: '一键分析和自动审查',
      summary: '整个工程一起跑，不用一个个点。',
      steps: [
        '顶部「一键分析」：对整个工程全部适用节点发起 AI 分析，抽屉里能看到这次分析的情况。',
        '「自动审查」：设置资料识别并挂载后实时审查，和/或每天定时扫描补漏；底部「立即执行全工程审查」马上跑一遍。'
      ],
      image: {
        src: shot('inspection-overview'),
        alt: '顶部的一键分析和自动审查',
        device: 'desktop',
        markers: [
          { n: 1, x: 82.4, y: 3.9 },
          { n: 2, x: 72.8, y: 3.9 }
        ]
      },
      jump: {
        label: '去「一键分析」',
        target: 'inspection-analysis',
        hint: '「一键分析」在这里，旁边是「自动审查」。'
      }
    },
    {
      id: 'important',
      title: '重要节点审查',
      summary: '挑几份文件、几个重点节点做专项审查。',
      steps: [
        '顶部切到「重要节点审查」。',
        '勾选要审的文件，点「分析适用节点」，再勾出重点节点，点「开始审查」。',
        '结果在下方「审查结果」，经你复核后才形成正式结论。'
      ],
      jump: {
        label: '去「重要节点审查」',
        target: 'inspection-view-tabs',
        hint: '在这里切换「重要节点审查」和「完整工作台」。'
      }
    },
    {
      id: 'assistant',
      title: '问 AI 助手',
      summary: '问资料要求、找证据、问系统怎么用。',
      steps: [
        '点右下角「AI审查」打开对话。',
        '可以问这个节点要什么资料、某份证书过没过期，也可以问某个按钮是干什么的。'
      ],
      jump: {
        label: '去「AI审查」助手',
        target: 'inspection-assistant',
        hint: '点这里打开 AI 助手。'
      }
    },
    {
      id: 'skill',
      title: '用节点审计 skill 在电脑上审节点',
      summary: '让电脑上的 AI 助手把节点逐项核一遍，给你第二意见。',
      steps: [
        '右上角账号菜单点「安装节点审计 skill」，把复制到的那句话发给你电脑上的 AI 助手（如 Claude Code），它会自己装好；之后对它说「审计 P-2026-GDLNG-002 节点 16」这样的话。',
        '浏览器会打开「授权 AIcheck 节点审计 skill」页：核对是你的监检账号，点「授权」。有效期和登录一样，到期再授权一次。',
        '它拉取节点资料、扫描件交平台识别，逐项给出符合、不符合、证据不足、需人工确认，附文件和页码；报告存在你电脑上。',
        '问你要不要同步时先看预览：写进平台的是待人工复核的 AI 审查发现草稿，不改节点状态。结论仍由你在节点页下。'
      ]
    },
    {
      id: 'messages',
      title: '看待办和消息',
      summary: '资料提交、补正反馈都会提醒你。',
      steps: [
        '点顶部「待办消息」，有「搜索」「待办」「消息」三个页签。',
        '点一条跳到对应的节点或资料；办完的待办点「完成」。'
      ],
      jump: { label: '去「待办消息」', target: 'topbar-messages', hint: '待办和消息都在这里。' }
    },
    {
      id: 'invite',
      title: '邀请各单位加入项目（项目负责人）',
      summary: '发一个链接，施工、无损、建设单位自己申请，你审核。',
      steps: [
        '顶部点「邀请成员」，链接和二维码已经生成好。',
        '点「复制」发到微信群，或截图二维码；对方用手机扫码就能填申请。',
        '有人申请时「待办消息」会提醒你，回到「邀请成员」审核。',
        '链接 7 天有效、最多 200 人；要作废旧链接就点「重新生成链接」。'
      ],
      jump: {
        label: '去「邀请成员」',
        target: 'inspection-invite',
        hint: '点这里打开邀请链接和申请列表。',
        emptyHint: '「邀请成员」只有项目负责人看得到。要邀请人请找项目负责人或管理员。'
      }
    },
    {
      id: 'review-join',
      title: '审核加入申请（项目负责人）',
      summary: '通过之后对方才能登录。',
      steps: REVIEW_JOIN_STEPS,
      jump: {
        label: '去「邀请成员」',
        target: 'inspection-invite',
        hint: '申请列表在「邀请成员」里。',
        emptyHint: '「邀请成员」只有项目负责人看得到。'
      }
    },
    {
      id: 'reset-member-password',
      title: '成员忘了密码（项目负责人）',
      summary: '施工、无损、建设单位的人登不上，在这里给一个临时密码。',
      steps: RESET_MEMBER_PASSWORD_STEPS,
      jump: {
        label: '去「邀请成员」',
        target: 'inspection-invite',
        hint: '「已加入的成员」在「邀请成员」里，申请列表下面。',
        emptyHint: '「邀请成员」只有项目负责人看得到。'
      }
    },
    SWITCH_PROJECT_TASK,
    ACCOUNT_TASK
  ],
  faq: [
    {
      q: '为什么不能选「满足要求」？',
      a: '必传审查点还缺已确认的资料证据。先挂接或确认证据，或者选「需补正」退回。'
    },
    {
      q: 'AI 的判定算不算结论？',
      a: '不算。AI 只给建议，节点的正式结论以你保存的「审查结论」为准。'
    },
    {
      q: '施工方说交了，我这里看不到？',
      a: '对方可能只上传、没有点「提交」。请对方在「待提交」里提交，或在「待办消息」的「搜索」里查一下。'
    },
    {
      q: '节点审计 skill 的结论能直接用吗？',
      a: '不能直接当正式结论。它是辅助意见，每项都附了出处，请你对照原件复核后，在节点页「审查结论」里下结论。'
    },
    {
      q: '怎么教施工方、无损检测、建设方用？',
      a: '在使用帮助顶部切到他们的角色，看他们那边的说明，照着讲就行。他们第一次登录时也会自动弹出引导。'
    },
    {
      q: '施工方说申请了，我这里没看到？',
      a: '只有项目负责人能看到申请。请确认对方用的是本项目的链接、链接没有过期；对方可以在链接里点「查看我的申请」看进度。'
    }
  ]
}

export const ADMIN_GUIDE: RoleGuide = {
  role: 'admin',
  roleLabel: '管理员',
  intro: '后台管项目、单位、账号和规则配置，不办理具体审查。',
  tour: [
    {
      path: '/admin/overview',
      target: 'admin-menu',
      hint: '左边是后台全部功能：基础管理、规则与业务配置、AI 知识库、运行与审计；平台管理员还有「平台」。'
    },
    {
      path: '/admin/overview',
      target: 'admin-new-project',
      hint: '新建项目从这里开始。只填项目名称就能立项，参建单位和人员不用在这里配。'
    },
    {
      path: '/admin/overview',
      target: 'admin-project-invite',
      hint: '每个项目这一行的「邀请成员」：发链接给各单位，他们自己申请；有待审核的会显示数字。',
      emptyHint: '还没有项目。立项后每个项目行上会有「邀请成员」。'
    },
    {
      path: '/admin/overview',
      target: 'admin-search',
      hint: '顶部搜索可以直接找项目、用户、权限；按 ⌘K（Windows 按 Ctrl+K）也能打开。'
    },
    {
      path: '/admin/overview',
      target: 'topbar-user',
      hint: ACCOUNT_SPOT.hint
    }
  ],
  tasks: [
    {
      id: 'projects',
      title: '新建项目',
      summary: '只填项目名称就能立项，其他都可以以后补。',
      steps: [
        '点「新建项目」，选压力管道类别，填项目名称。',
        '参建单位、初始成员都是选填：可以直接打字填单位名，也可以空着，之后由各单位自己申请。',
        '点「立项」，会自动打开「邀请成员」，链接和二维码已经生成好。'
      ],
      image: {
        src: shot('admin-projects'),
        alt: '后台项目管理',
        device: 'desktop',
        markers: [{ n: 1, x: 95.3, y: 11.9 }]
      },
      jump: {
        label: '打开「项目管理」页',
        path: '/admin/overview',
        target: 'admin-new-project',
        hint: '点这里新建项目。'
      }
    },
    {
      id: 'invite',
      title: '邀请各单位的人加入项目',
      summary: '不用你替他们建单位、建账号。',
      steps: [
        '在项目这一行点「邀请成员」。',
        '点「复制」把链接发到施工、无损、建设单位的群里，或者让他们扫二维码。',
        '对方自己填姓名、手机号、单位和角色，设好密码提交。',
        '有人申请时「邀请成员」上会显示数字，「待办消息」也会提醒。'
      ],
      jump: {
        label: '去「邀请成员」',
        path: '/admin/overview',
        target: 'admin-project-invite',
        hint: '每个项目这一行都有「邀请成员」。',
        emptyHint: '还没有项目。先新建一个项目，行上就会有「邀请成员」。'
      }
    },
    {
      id: 'review-join',
      title: '审核加入申请',
      summary: '通过之后对方才能登录，并且只看得到这个项目。',
      steps: REVIEW_JOIN_STEPS,
      jump: {
        label: '去「邀请成员」',
        path: '/admin/overview',
        target: 'admin-project-invite',
        hint: '点「邀请成员」，申请列表在下面。',
        emptyHint: '还没有项目。'
      }
    },
    {
      id: 'reset-member-password',
      title: '成员忘了密码',
      summary:
        '施工、无损、建设单位的成员在项目的「邀请成员」里就能重置；监检人员在「组织用户」里改。',
      steps: RESET_MEMBER_PASSWORD_STEPS,
      jump: {
        label: '去「邀请成员」',
        path: '/admin/overview',
        target: 'admin-project-invite',
        hint: '点项目行上的「邀请成员」，「已加入的成员」在申请列表下面。',
        emptyHint: '还没有项目。'
      }
    },
    {
      id: 'manage-projects',
      title: '查找、修改、归档项目',
      summary: '项目信息写错了、项目结束了。',
      steps: [
        '用搜索框按项目名称、编号或区域查找。',
        '每行「详情」看状态、成员和登记资料，「编辑」改信息。',
        '「更多」里可以归档或删除；有业务数据的项目只能归档。'
      ],
      image: {
        src: shot('admin-projects'),
        alt: '后台项目管理',
        device: 'desktop',
        markers: [
          { n: 1, x: 37.5, y: 41.7 },
          { n: 2, x: 91, y: 53.3 }
        ]
      },
      jump: {
        label: '打开「项目管理」页',
        path: '/admin/overview',
        target: 'admin-new-project',
        hint: '项目列表在这一页。'
      }
    },
    {
      id: 'org',
      title: '改单位名、停用单位（一般用不到）',
      summary: '审核时会自动建单位；只有要改名、合并或停用时才来这里。',
      steps: [
        '在「组织用户」的「组织单位」里找到这个单位，点「编辑」改名或改状态。',
        '同一家公司建成了两个单位（简称和全称），把其中一个停用，以后审核选「并入」另一个。',
        '也可以在这里手动「新增组织」「新增用户」，适合个别不方便自己申请的人。'
      ],
      image: {
        src: shot('admin-org'),
        alt: '后台组织用户',
        device: 'desktop',
        markers: [
          { n: 1, x: 83.5, y: 55.3 },
          { n: 3, x: 94.4, y: 28.4 }
        ]
      },
      jump: {
        label: '打开「组织用户」页',
        path: '/admin/org',
        target: 'admin-new-org',
        hint: '单位和账号都在这一页。'
      }
    },
    {
      id: 'password',
      title: '重置密码、停用账号',
      summary: '有人忘了密码或离职时。',
      steps: [
        '在「用户与角色」找到这个人，点「编辑」。',
        '填「重置密码」并保存，对方用新密码登录；不再使用的账号把「状态」改掉或删除。'
      ],
      jump: {
        label: '去「用户与角色」',
        path: '/admin/org',
        target: 'admin-new-user',
        hint: '用户都在「用户与角色」这一栏。'
      }
    },
    {
      id: 'feedback',
      title: '处理意见反馈',
      summary: '大家在使用中提交的问题。',
      steps: [
        '左边「运行与审计」→「意见反馈」，按状态筛选。',
        '点一条，写「回复提交人」和「处理说明」，改状态后点「保存」，提交人能看到回复。',
        '本院解决不了的点「送平台」，写清「给平台的说明」。'
      ],
      jump: {
        label: '打开「意见反馈」页',
        path: '/admin/feedback',
        target: 'admin-feedback',
        hint: '反馈都在这里。'
      }
    },
    {
      id: 'rule-updates',
      title: '给旧项目升级规则',
      summary: '规则修好了，旧项目要升级才生效。',
      steps: [
        '项目建立时冻结了当时的业务规则，平台后来修好的规则不会自动用到旧项目上。',
        '在「规则升级」看每个项目的规则版本和改了什么，勾选项目后点「升级选中项目」。'
      ],
      jump: {
        label: '打开「规则升级」页',
        path: '/admin/rule-updates',
        target: 'admin-rule-updates',
        hint: '各项目的规则版本在这里。'
      }
    },
    {
      id: 'policies',
      title: '设本院审查口径',
      summary: '几处各院判法可能不同的地方。',
      steps: [
        '「审查口径」列出几处各院判法可能不同的地方，例如证书在审查日已过期、但项目没有施工期。',
        '在「本院口径」里选一种，点「保存本院口径」；不设就跟随平台默认。选项只能更严或同等。'
      ],
      jump: {
        label: '打开「审查口径」页',
        path: '/admin/review-policies',
        target: 'admin-review-policies',
        hint: '本院口径在这里设。'
      }
    },
    {
      id: 'platform',
      title: '平台管理员：开通特检院、处理改进任务',
      summary: '只有平台管理员能看到。',
      steps: [
        '左边「平台」→「特检院管理」：开通新的特检院和院管理员。',
        '「改进任务」：审批各院送上来的问题。'
      ],
      jump: {
        label: '去左边「平台」菜单',
        path: '/admin/overview',
        target: 'admin-menu',
        hint: '「平台」分组在左边菜单最下面。'
      }
    },
    ACCOUNT_TASK
  ],
  faq: [
    {
      q: '管理员能直接审节点吗？',
      a: '不能。后台只管配置，审查由监检人员在监检工作台办理。'
    },
    {
      q: '改了规则，旧项目为什么没变？',
      a: '项目建立时冻结了当时的规则，要在「规则升级」里升级后才生效。'
    },
    {
      q: '在哪查谁做了什么？',
      a: '左边「运行与审计」→「审计日志」。'
    },
    {
      q: '还要先建单位、再建账号吗？',
      a: '不用。建项目、发邀请链接就行，各单位的人自己申请，你审核时系统自动建单位和账号。「组织用户」只在改名、停用时用。'
    },
    {
      q: '审核时提示「单位名不一致」怎么选？',
      a: '同一家公司（简称、全称、错字）选「并入」已有单位；确实是另一家公司选「算作新单位」。资料按单位隔离，选错会让两家互相看到资料或看不到。'
    },
    {
      q: '申请人说一直没通过？',
      a: '看项目行「邀请成员」上的数字，进去审核。申请人在链接里点「查看我的申请」能看到进度和拒绝原因。'
    }
  ]
}
