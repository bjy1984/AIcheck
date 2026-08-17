/**
 * 施工方上传资料的**分类口径** —— 唯一一份。
 *
 * ## 为什么单独成文件
 *
 * 这份表既是「上传引导」（告诉施工方这一类该传什么），也是「自动分类」的
 * 依据（把上传的文件归到某一类）。它原先埋在 SFC 里，没法单独跑测试，
 * 而分类错了的表现是**资料明明传了，却被判成缺项** —— 界面上看不出来。
 *
 * ## 改这份表时注意
 *
 * - 关键词要够具体。通用词（「许可证」「材料」）会把别的类别的文件吸过来。
 * - 类别归属要和后端 backend/config/material_review_points.json 的
 *   materialCategory 保持一致，否则施工方按一套分类传，规则按另一套取证。
 */

export type ContractorMaterialRequirement = {
  category: string
  requiredItems: string
  keywords: string[]
  uploadHint: string
}

export const CONTRACTOR_MATERIAL_REQUIREMENTS: ContractorMaterialRequirement[] = [
  {
    /* 这一类是**参与单位自身**的资质：施工单位、设计单位、无损检测机构、焊工。
     * 元件制造许可证不在这里——它证明的是「这批元件的制造方有资格造」，
     * 属于材料证明。后端 material_review_points.json 里那两条的
     * businessModule 本来就写着「材料」，只有 materialCategory 落在了资质证照。 */
    category: '资质证照',
    requiredItems: '施工单位安装许可证、设计单位许可证或资质、无损检测机构核准证、焊工资格证',
    keywords: ['安装许可', '设计许可', '核准证', '焊工', '资格证', '许可资质'],
    uploadHint: '建议上传完整页面，清晰显示单位名称、许可范围、证书编号和有效期。'
  },
  {
    category: '设计资料',
    requiredItems:
      '图纸目录、设计说明、数据表、材料表、布置图、强度或应力计算书、设计变更及审批资料',
    keywords: ['设计', '图纸', '施工图', '说明书', '数据表', '特性表', '材料表', '计算书'],
    uploadHint: '建议按图号和版本归集，并保留图签、签字盖章页以及对应的变更记录。'
  },
  {
    category: '施工方案',
    requiredItems:
      '施工组织设计、进度计划、施工方案及审批、安全与技术交底、试压/泄漏/吹扫清洗专项方案',
    keywords: ['施工方案', '施工组织', '试压方案', '泄漏试验', '吹扫', '清洗方案'],
    uploadHint: '建议将正文、编制审核批准页及建设单位意见作为一套资料上传。'
  },
  {
    category: '材料证明与复验',
    requiredItems:
      '产品质量证明、出厂检验、元件制造许可证及相关证明、制造监检或型式试验、到货验收、抽样复验、标志移植、材料代用资料',
    keywords: [
      '质量证明',
      '材质',
      '材料',
      '复验',
      '出厂检验',
      '验收',
      '标志移植',
      '材料代用',
      '制造许可',
      '元件制造',
      '型式试验',
      '制造监检'
    ],
    uploadHint: '建议按材料类别、规格和批号归集；复印件应保留确认章，并能追溯到使用部位。'
  },
  {
    category: '安全附件与阀门',
    requiredItems: '阀门质量证明和试验记录、安全阀/爆破片/紧急切断阀产品资料、安装记录及校验资料',
    keywords: ['安全阀', '爆破片', '紧急切断', '阀门', '校验', '压力试验'],
    uploadHint: '建议资料清晰标注设备编号、规格参数、安装位置、试验或校验结论及签字日期。'
  },
  {
    category: '焊接资料',
    requiredItems:
      'WPS/PQR、焊材质量证明及烘干/领用/退库记录、组对记录、焊接记录、焊缝编号、外观检查、返修资料',
    keywords: ['焊接', '焊材', 'WPS', 'PQR', '焊缝', '返修', '组对'],
    uploadHint: '建议按焊缝编号成套整理，使焊工、工艺、焊材、检验和返修记录能够相互对应。'
  },
  {
    category: '热处理资料',
    requiredItems: '热处理工艺卡、工艺评定、仪表校验资料、热处理曲线、热处理报告、硬度报告',
    keywords: ['热处理', '硬度', '温控', '热电偶', '曲线'],
    uploadHint: '项目涉及热处理时，建议将工艺、设备仪表、过程曲线、结果报告和硬度记录成套上传。'
  },
  {
    category: '防腐保温资料',
    requiredItems: '防腐/保温材料质量证明、施工与验收记录、补口补伤记录、电火花检测、阴极保护资料',
    keywords: ['防腐', '保温', '涂料', '补口', '补伤', '电火花', '阴极保护'],
    uploadHint: '建议按管段或线路归集材料、施工、检测与验收资料，并注明材料批号和施工部位。'
  },
  {
    category: '安装交工资料',
    requiredItems:
      '元件进场检查、预制与安装记录、支吊架、膨胀装置、穿跨越、套管绝缘、单线图、静电接地、交工资料',
    keywords: [
      '交工',
      '安装记录',
      '预制',
      '支吊架',
      '膨胀',
      '穿跨越',
      '套管绝缘',
      '单线图',
      '元件检查',
      '接地'
    ],
    uploadHint: '建议按管线号或单线图整理过程记录，确保记录中的设备、管段和安装位置可对应。'
  },
  {
    category: '试验与吹扫资料',
    requiredItems: '压力表/温度仪表检定校准、耐压试验、泄漏试验、吹扫清洗方案与记录、现场确认资料',
    keywords: ['耐压', '压力表', '泄漏', '吹扫', '清洗', '试验记录', '试验报告'],
    uploadHint: '建议将方案、仪表校准、过程记录、结果签认和现场照片等按同一次试验成套上传。'
  }
]

/* 取**匹配到的最长关键词**所属的类别，不是第一个命中的类别。
 *
 * 原先是「首个匹配即胜」，而类别是按数组顺序排的。「资质证照」排第一，
 * 它的关键词里有通用的「许可证」——于是「元件制造许可证」永远被它吃掉，
 * 落进资质证照，而它其实属于材料证明。**加关键词是没用的**：
 * 不管往材料那一类加多少词，第一条仍然先命中。
 *
 * 关键词越长越具体（「制造许可」比「许可证」具体），所以按长度取胜者。
 * 平手时保持数组顺序，结果才是确定的——否则同一个文件名两次分类可能不同。
 */
export const inferMaterialCategory = (text: string): string => {
  const normalized = String(text || '').toLowerCase()
  let best: { category: string; length: number } | null = null
  for (const item of CONTRACTOR_MATERIAL_REQUIREMENTS) {
    for (const keyword of item.keywords) {
      const needle = keyword.toLowerCase()
      if (!needle || !normalized.includes(needle)) continue
      if (!best || needle.length > best.length) {
        best = { category: item.category, length: needle.length }
      }
    }
  }
  return best?.category || '其他资料'
}
