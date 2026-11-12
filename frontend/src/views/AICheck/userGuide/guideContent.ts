/** 各角色的使用帮助内容（2026-11-04 首版）。
 *
 * 只写页面上真有的按钮和标题，照抄界面文字；界面改了这里要跟着改
 * （userGuide.test.ts 会核对 data-guide 锚点在页面里还在）。
 * 施工方、无损检测、建设方三份不出现「AI」「人工智能」。 */
import type { GuideRole, RoleGuide } from './guideTypes'
import { ACCOUNT_SPOT, ACCOUNT_TASK, PROJECT_SPOT, SWITCH_PROJECT_TASK } from './guideCommon'
import { ADMIN_GUIDE, INSPECTION_GUIDE } from './guideContentStaff'

const shot = (name: string) => new URL(`./images/${name}.jpg`, import.meta.url).href

const MESSAGES_TASK = {
  id: 'messages',
  title: '看待办和消息',
  summary: '被退回、审核有结果时，会在这里提醒你。',
  steps: [
    '点顶部的「待办消息」，数字是还没处理的条数。',
    '「待办」是要你去办的事，「消息」是通知；点一条就跳到对应的地方。'
  ],
  jump: {
    label: '去「待办消息」',
    target: 'topbar-messages',
    hint: '待办和消息都在这里，数字是还没处理的条数。'
  }
}

/** 对外三个角色共用的常见问题 */
const COMMON_FAQ = [
  {
    q: '同事也要用，怎么让他加入？',
    a: '请项目负责人把「邀请链接」或二维码发给他。他打开后自己填姓名、单位和角色，审核通过就能登录，不用你帮他填。'
  },
  {
    q: '忘了密码怎么办？',
    a: '请项目负责人或管理员在后台帮你重置，然后用新密码登录，进去后可以在账号菜单「修改密码」改成自己的。'
  },
  {
    q: '手机上能用吗？',
    a: '能。用手机浏览器打开同一个网址登录就行，上传时可以直接拍照。'
  }
]

const CONTRACTOR_GUIDE: RoleGuide = {
  role: 'contractor',
  roleLabel: '施工方',
  intro: '你要做的就三件事：把资料传上来，提交给监检审核，处理监检退回的意见。手机、电脑都能用。',
  tour: [
    PROJECT_SPOT,
    {
      target: 'contractor-status',
      hint: '这三个数是你要办的事：需补正（被监检退回）、待提交（传了还没交）、审核中（监检在看）。点一个数，下面只显示那一类。'
    },
    {
      target: 'contractor-upload',
      hint: '传资料点这个大按钮。手机上可以直接拍照，一次能选多份，系统会自动认出资料类别。'
    },
    {
      target: 'contractor-feedback',
      hint: '被监检退回的资料会以红色卡片出现在这里，按卡片上的意见补交或反馈。',
      emptyHint: '现在没有被监检退回的资料。以后有退回，会以红色卡片出现在上传按钮下面。'
    },
    {
      target: 'contractor-pending',
      hint: '传上来的资料先在这里等你确认，点「提交」或「全部提交」才会交给监检。',
      emptyHint: '现在没有待提交的资料。传完资料后，会先出现在「待提交」里等你提交。'
    },
    {
      target: 'contractor-files',
      hint: '传过的资料都在「我的资料」里。点文件名查看，点右边「⋯」可以提交、替换、删除。'
    },
    {
      target: 'topbar-messages',
      hint: '有退回、审核结果时，「待办消息」会提醒你。'
    },
    {
      target: 'contractor-guide',
      hint: '不知道该传什么，点这里看上传指引：按类别列出要交的资料和要求。'
    },
    ACCOUNT_SPOT
  ],
  tasks: [
    {
      id: 'upload',
      title: '上传资料',
      summary: '拍照或选文件，一次可以传多份。',
      steps: [
        '点「拍照或选择文件上传」。手机上可以直接拍照，也可以从相册或文件里选，一次能选多份。',
        '选好后点「上传 N 个文件」，等它传完。',
        '传好的资料出现在「待提交」里，类别由系统自动识别。'
      ],
      image: {
        src: shot('contractor-upload'),
        alt: '施工方首页：三个数字、上传按钮',
        device: 'phone',
        markers: [
          { n: 1, x: 4, y: 13 },
          { n: 3, x: 4, y: 38 }
        ]
      },
      jump: {
        label: '去「拍照或选择文件上传」',
        target: 'contractor-upload',
        hint: '点这个按钮选文件或拍照。'
      }
    },
    {
      id: 'submit',
      title: '提交给监检',
      summary: '传上来的资料要提交，监检才看得到。',
      steps: [
        '在「待提交」里找到刚传的文件。',
        '点文件右边的「提交」；要一起交就点「全部提交」。',
        '提交后状态变成「审核中」，等监检审核。'
      ],
      image: {
        src: shot('contractor-pending'),
        alt: '待提交列表和全部提交按钮',
        device: 'phone',
        markers: [
          { n: 1, x: 6, y: 23 },
          { n: 2, x: 79, y: 6 }
        ]
      },
      jump: {
        label: '去「待提交」',
        target: 'contractor-pending',
        hint: '这里是传了还没交的资料，点「提交」或「全部提交」。',
        emptyHint: '现在没有待提交的资料。传完资料后，会先出现在「待提交」里。'
      }
    },
    {
      id: 'returned',
      title: '处理监检退回',
      summary: '红色卡片是被退回、需要你补正的资料。',
      steps: [
        '看卡片上的「监检意见」，弄清要补什么。',
        '要补文件就点「补交资料」，上传改好的文件。',
        '补完点「提交反馈」，写一句说明交回给监检。',
        '要用的文件已经传过了，就点「关联已有文件」挂上去，不用重传。'
      ],
      image: {
        src: shot('contractor-returned'),
        alt: '监检退回的红色卡片',
        device: 'phone',
        markers: [
          { n: 1, x: 4.7, y: 33 },
          { n: 2, x: 43.3, y: 45.6 },
          { n: 3, x: 69, y: 45.6 },
          { n: 4, x: 36.5, y: 64 }
        ]
      },
      jump: {
        label: '去「监检退回」',
        target: 'contractor-feedback',
        hint: '被退回的资料在这里，按卡片上的意见处理。',
        emptyHint: '现在没有被监检退回的资料。'
      }
    },
    {
      id: 'files',
      title: '查找、替换或删除资料',
      summary: '所有传过的资料都在「我的资料」。',
      steps: [
        '点「全部 / 待提交 / 审核中 / 需补正」只看某一类；要按名字找，点「搜索与筛选」。',
        '点文件名打开查看。',
        '点右边「⋯」：提交、替换文件、选择环节、删除。已经提交的资料不能直接替换或删除，要改请按监检退回走补正。'
      ],
      image: {
        src: shot('contractor-files'),
        alt: '我的资料列表和更多操作菜单',
        device: 'phone',
        markers: [
          { n: 1, x: 5, y: 14 },
          { n: 2, x: 9.8, y: 34.8 },
          { n: 3, x: 82.6, y: 31.5 }
        ]
      },
      jump: {
        label: '去「我的资料」',
        target: 'contractor-files',
        hint: '传过的所有资料都在这里。'
      }
    },
    MESSAGES_TASK,
    {
      id: 'guide',
      title: '不知道该传什么',
      summary: '按资料类别列出了要交的东西和要求。',
      steps: [
        '页面最下面点「不知道传什么？看上传指引」。',
        '按类别看要交哪些资料、有什么要求；直接上传就行，类别系统会自动识别。'
      ],
      jump: { label: '去「上传指引」', target: 'contractor-guide', hint: '点这里展开上传指引。' }
    },
    SWITCH_PROJECT_TASK,
    ACCOUNT_TASK
  ],
  faq: [
    {
      q: '传上来了，为什么监检说没看到？',
      a: '资料要「提交」才会交给监检。看看「待提交」里是不是还有没交的。'
    },
    {
      q: '传错了文件怎么办？',
      a: '还没提交的：在「我的资料」里点「⋯」→「替换文件」或「删除」。已经提交的不能直接改，请联系监检人员退回后再补正。'
    },
    {
      q: '类别后面写着「推测」是什么意思？',
      a: '系统是按文件名猜的类别，可能不准。打开文件查看时可以改成正确的类别。'
    },
    {
      q: '「提交」是灰的，点不了？',
      a: '文件还在上传或处理中，等处理完就能提交；已经提交过的也不能重复提交。'
    },
    {
      q: '一份资料要传几次？',
      a: '传一次就行。同一份资料用在好几个环节，系统会自动关联，不用重复上传。'
    },
    ...COMMON_FAQ
  ]
}

const NDT_GUIDE: RoleGuide = {
  role: 'ndt',
  roleLabel: '无损检测',
  intro: '你要做的：传检测报告、底片、记录等资料并提交给监检；监检有反馈时按要求补充或回复。',
  tour: [
    PROJECT_SPOT,
    {
      target: 'ndt-feedback',
      hint: '监检反馈放在最上面，红色卡片是要你处理的，注意期限。',
      emptyHint: '现在没有监检反馈。有反馈时会以红色卡片出现在页面最上面。'
    },
    {
      target: 'ndt-actions',
      hint: '三个常用操作：上传检测报告、登记底片编号、上传其他资料。'
    },
    {
      target: 'ndt-stats',
      hint: '已登记的底片、记录、报告有多少，还有几份资料等你提交。'
    },
    {
      target: 'ndt-checklist',
      hint: '还没传的资料类型列在这里，点那一行的「上传」就传这一类。'
    },
    {
      target: 'ndt-uploaded',
      hint: '传过的资料都在「已上传」。点「提交」交给监检；「⋯」里还能调整适用的业务规则。'
    },
    {
      target: 'topbar-messages',
      hint: '监检有反馈、审核有结果时，「待办消息」会提醒你。'
    },
    ACCOUNT_SPOT
  ],
  tasks: [
    {
      id: 'feedback',
      title: '处理监检反馈',
      summary: '红色卡片是监检要你补充或说明的事，有期限。',
      steps: [
        '看卡片上的标题、说明和期限。',
        '要补资料就点「补充资料」上传。',
        '补完点「回复反馈」，写好补正说明，点「提交反馈」。'
      ],
      image: {
        src: shot('ndt-feedback'),
        alt: '监检反馈红色卡片和三个常用操作',
        device: 'phone',
        markers: [
          { n: 1, x: 5.3, y: 18.1 },
          { n: 2, x: 8.8, y: 38.7 },
          { n: 3, x: 52.3, y: 38.7 }
        ]
      },
      jump: {
        label: '去「监检反馈」',
        target: 'ndt-feedback',
        hint: '监检反馈在这里，按卡片上的要求处理。',
        emptyHint: '现在没有监检反馈。'
      }
    },
    {
      id: 'report',
      title: '上传检测报告',
      summary: '报告传上来后要提交，监检才看得到。',
      steps: ['点「上传检测报告」，选择报告文件上传。', '传完在「已上传」里找到它，点「提交」。'],
      jump: {
        label: '去「上传检测报告」',
        target: 'ndt-actions',
        hint: '第一个按钮就是「上传检测报告」。'
      }
    },
    {
      id: 'film',
      title: '登记底片编号',
      summary: '一张底片登记一条，和焊口对应起来。',
      steps: [
        '点「登记底片编号」。',
        '填底片编号、焊口编号、检测方法（这三项必填），其他按实际填。',
        '点「登记底片」保存，上面「底片」的数字会加一。'
      ],
      jump: {
        label: '去「登记底片编号」',
        target: 'ndt-actions',
        hint: '中间的按钮是「登记底片编号」。'
      }
    },
    {
      id: 'materials',
      title: '上传其他资料',
      summary: '资质证书、质量手册、检定报告等，按类型传。',
      steps: [
        '在「还缺的资料」里找到要传的类型；点「展开全部 22 种」能看到所有类型。',
        '点那一行的「上传」，选择文件。',
        '已传过的类型会显示份数，点份数可以看是哪几份。'
      ],
      image: {
        src: shot('ndt-checklist'),
        alt: '还缺的资料列表',
        device: 'phone',
        markers: [
          { n: 1, x: 6.5, y: 22.3 },
          { n: 2, x: 77.9, y: 15.6 }
        ]
      },
      jump: {
        label: '去「还缺的资料」',
        target: 'ndt-checklist',
        hint: '还没传的资料类型在这里，点「上传」。'
      }
    },
    {
      id: 'submit',
      title: '提交给监检',
      summary: '传上来的资料要提交才会进入审查。',
      steps: [
        '在「已上传」里找到文件。',
        '点「提交」；多份一起交点「全部提交」。',
        '状态变成「待审查」就是交上去了。'
      ],
      image: {
        src: shot('ndt-uploaded'),
        alt: '已上传列表',
        device: 'phone',
        markers: [
          { n: 1, x: 10.7, y: 34.1 },
          { n: 2, x: 64, y: 50.3 }
        ]
      },
      jump: {
        label: '去「已上传」',
        target: 'ndt-uploaded',
        hint: '传过的资料在这里，点「提交」或「全部提交」。'
      }
    },
    {
      id: 'rules',
      title: '调整适用的业务规则',
      summary: '一份资料用在哪些规则上，可以自己调。',
      steps: [
        '在「已上传」里点文件右边的「⋯」→「调整业务规则」。',
        '勾选这份资料适用的规则，点「保存」。只有草稿或需补正的文件能改，提交后不能再改。'
      ],
      jump: {
        label: '去「已上传」',
        target: 'ndt-uploaded',
        hint: '点文件右边的「⋯」，选「调整业务规则」。'
      }
    },
    MESSAGES_TASK,
    SWITCH_PROJECT_TASK,
    ACCOUNT_TASK
  ],
  faq: [
    {
      q: '「提交」是灰的，点不了？',
      a: '文件还在上传或处理中，等处理完就能提交；已经提交过的不能重复提交。'
    },
    {
      q: '传错了文件怎么办？',
      a: '还没提交的可以重新上传正确的文件；已经提交的请联系监检人员退回后再补正。'
    },
    {
      q: '「资料处理」一直在排队？',
      a: '文件已经传上来了，系统还在读取内容，稍等一会儿刷新就好；长时间不动请联系监检人员。'
    },
    ...COMMON_FAQ
  ]
}

const OWNER_GUIDE: RoleGuide = {
  role: 'owner',
  roleLabel: '建设方',
  intro: '这里只看不改：项目审查到哪了、哪些环节要关注、报告和归档资料在哪下载。',
  tour: [
    PROJECT_SPOT,
    {
      target: 'owner-progress',
      hint: '项目整体进度和各状态的环节数，点一个状态，下面只显示那一类环节。'
    },
    {
      target: 'owner-attention',
      hint: '需要关注的环节放在这里，点进去看原因。',
      emptyHint: '现在没有需要关注的环节。'
    },
    {
      target: 'owner-news',
      hint: '最近的审查动态，点「全部」看所有消息。'
    },
    {
      target: 'owner-reports',
      hint: '监检报告和归档资料在这里查看、下载。'
    },
    {
      target: 'owner-nodes',
      hint: '全部环节都在这里，点一个环节看它的资料和审查情况。'
    },
    {
      target: 'topbar-messages',
      hint: '审查有进展、报告签发时，「待办消息」会提醒你。'
    },
    ACCOUNT_SPOT
  ],
  tasks: [
    {
      id: 'progress',
      title: '看项目进度',
      summary: '一眼看出审查到哪、还差什么。',
      steps: [
        '最上面是整体进度和「已通过 / 审查中 / 需补正 / 待提交」的环节数。',
        '点一个状态，下面「全部节点」只显示那一类。',
        '点「参建单位」可以看建设、施工、监检各单位。'
      ],
      image: {
        src: shot('owner-home'),
        alt: '建设方首页：进度和状态',
        device: 'phone',
        markers: [
          { n: 1, x: 4.5, y: 17.5 },
          { n: 2, x: 4.5, y: 30 },
          { n: 3, x: 73, y: 48.6 }
        ]
      },
      jump: { label: '去「项目进度」', target: 'owner-progress', hint: '整体进度在这里。' }
    },
    {
      id: 'node',
      title: '看某个环节的资料',
      summary: '每个环节交了哪些资料、审查结果如何。',
      steps: [
        '在「全部节点」里点一个环节。',
        '弹出的页面里列着这个环节的资料和审查情况，点文件可以查看。'
      ],
      jump: { label: '去「全部节点」', target: 'owner-nodes', hint: '点一个环节看它的资料。' }
    },
    {
      id: 'reports',
      title: '下载报告和归档资料',
      summary: '节点通过、报告签发后会出现在这里。',
      steps: [
        '在「报告与归档」里点报告的「查看」，或归档资料的「下载」。',
        '要全部资料就点「下载完整归档包」。'
      ],
      jump: { label: '去「报告与归档」', target: 'owner-reports', hint: '报告和归档资料在这里。' }
    },
    {
      id: 'news',
      title: '看最新动态',
      summary: '审查有进展时会出现在这里和「待办消息」里。',
      steps: ['「最新动态」列出最近的几条，点「全部」看全部消息。', '也可以点顶部的「待办消息」。'],
      jump: { label: '去「最新动态」', target: 'owner-news', hint: '最近的动态在这里。' }
    },
    SWITCH_PROJECT_TASK,
    ACCOUNT_TASK
  ],
  faq: [
    {
      q: '可以在这里改资料或给意见吗？',
      a: '建设方账号只能查看。资料由施工方、无损检测单位上传，审查由监检人员办理。'
    },
    {
      q: '「报告与归档」是空的？',
      a: '环节通过审查、报告签发后才会出现在这里。'
    },
    ...COMMON_FAQ
  ]
}

export const GUIDE_ROLES: GuideRole[] = ['inspection', 'contractor', 'ndt', 'owner', 'admin']

const GUIDES: Record<GuideRole, RoleGuide> = {
  inspection: INSPECTION_GUIDE,
  contractor: CONTRACTOR_GUIDE,
  ndt: NDT_GUIDE,
  owner: OWNER_GUIDE,
  admin: ADMIN_GUIDE
}

export const guideForRole = (role: GuideRole): RoleGuide => GUIDES[role]

export const hasUserGuide = (role?: string) =>
  (GUIDE_ROLES as string[]).includes(String(role || ''))
