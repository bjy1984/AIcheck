# Scan 知识类型分类与 OCR 结果

- 处理时间：2026-06-24
- 分类依据：`knowledge_governance_tooling_plan.md` 中的五类知识来源：图纸、设计文件、现场照片、证书 OCR、标准规范。
- OCR 方法：PDF 先用 Poppler 渲染为图片，再用 macOS Vision 中英文 OCR；HEIC 直接用 Vision OCR。
- 输出文本目录：`output/ocr/texts/`
- 逐行溯源记录：`output/ocr/ocr_records.jsonl`
- 分类表：`output/ocr/classification.csv`

## 分类汇总

| 知识类型 | 文件数 | 页/图数 | OCR 行数 | 平均置信度 |
|---|---:|---:|---:|---:|
| 图纸类数据 | 5 | 5 | 128 | 0.4310 |
| 设计文件类数据 | 18 | 36 | 2564 | 0.6209 |
| 现场照片类数据 | 0 | 0 | 0 | 0.0000 |
| 证书 OCR 类数据 | 7 | 66 | 5342 | 0.6329 |
| 标准规范类数据 | 0 | 0 | 0 | 0.0000 |
| 待人工复核 | 0 | 0 | 0 | 0.0000 |

## 文件级结果

| 文件 | 知识类型 | 页/图数 | OCR 行数 | 字符数 | 平均置信度 | 分类证据 | OCR 文本 |
|---|---|---:|---:|---:|---:|---|---|
| 20260623104523.pdf | 证书 OCR 类数据 | 1 | 29 | 379 | 0.6621 | 主类型命中：特种设备安装改造维修许可证 | `output/ocr/texts/20260623104523.txt` |
| 20260623104555.pdf | 证书 OCR 类数据 | 5 | 178 | 1956 | 0.5854 | 主类型命中：特种设备制造许可证 | `output/ocr/texts/20260623104555.txt` |
| 20260623104703.pdf | 证书 OCR 类数据 | 7 | 628 | 6383 | 0.4398 | 主类型命中：交工/质量证明资料 | `output/ocr/texts/20260623104703.txt` |
| 20260623104730.pdf | 证书 OCR 类数据 | 24 | 1961 | 12570 | 0.7420 | 主类型命中：交工/质量证明资料 | `output/ocr/texts/20260623104730.txt` |
| 20260623104828.pdf | 证书 OCR 类数据 | 12 | 885 | 6652 | 0.6861 | 主类型命中：质量证明书 | `output/ocr/texts/20260623104828.txt` |
| 20260623105454.pdf | 设计文件类数据 | 19 | 691 | 10863 | 0.7253 | 主类型命中：施工方案 | `output/ocr/texts/20260623105454.txt` |
| 20260623105534.pdf | 证书 OCR 类数据 | 12 | 1253 | 9674 | 0.5966 | 主类型命中：特种设备制造许可证 | `output/ocr/texts/20260623105534.txt` |
| 20260623105636.pdf | 证书 OCR 类数据 | 5 | 408 | 2098 | 0.7184 | 主类型命中：射线检测报告 | `output/ocr/texts/20260623105636.txt` |
| IMG_6508.heic | 设计文件类数据 | 1 | 39 | 363 | 0.4462 | 主类型命中：材料表 | `output/ocr/texts/IMG_6508.txt` |
| IMG_6509.heic | 设计文件类数据 | 1 | 274 | 1620 | 0.6489 | 主类型命中：管道特性表 | `output/ocr/texts/IMG_6509.txt` |
| IMG_6510.heic | 图纸类数据 | 1 | 41 | 486 | 0.3707 | 主类型命中：管道及仪表流程图 | `output/ocr/texts/IMG_6510.txt` |
| IMG_6511.heic | 设计文件类数据 | 1 | 113 | 1328 | 0.6619 | 主类型命中：压力管道强度计算书 | `output/ocr/texts/IMG_6511.txt` |
| IMG_6512.heic | 设计文件类数据 | 1 | 58 | 627 | 0.6052 | 主类型命中：工艺设计说明书 | `output/ocr/texts/IMG_6512.txt` |
| IMG_6513.heic | 设计文件类数据 | 1 | 100 | 947 | 0.7210 | 主类型命中：设备一览表 | `output/ocr/texts/IMG_6513.txt` |
| IMG_6514.heic | 设计文件类数据 | 1 | 100 | 916 | 0.6440 | 主类型命中：工艺设计说明书 | `output/ocr/texts/IMG_6514.txt` |
| IMG_6515.heic | 设计文件类数据 | 1 | 67 | 871 | 0.6060 | 主类型命中：工艺设计说明书 | `output/ocr/texts/IMG_6515.txt` |
| IMG_6516.heic | 设计文件类数据 | 1 | 72 | 936 | 0.5792 | 主类型命中：设计说明书 | `output/ocr/texts/IMG_6516.txt` |
| IMG_6517.heic | 设计文件类数据 | 1 | 84 | 1061 | 0.6310 | 主类型命中：工艺设计说明书 | `output/ocr/texts/IMG_6517.txt` |
| IMG_6518.heic | 设计文件类数据 | 1 | 69 | 940 | 0.5783 | 主类型命中：工艺设计说明书 | `output/ocr/texts/IMG_6518.txt` |
| IMG_6519.heic | 设计文件类数据 | 1 | 80 | 1014 | 0.6512 | 主类型命中：工艺设计说明书 | `output/ocr/texts/IMG_6519.txt` |
| IMG_6520.heic | 设计文件类数据 | 1 | 112 | 889 | 0.6929 | 主类型命中：综合材料表 | `output/ocr/texts/IMG_6520.txt` |
| IMG_6521.heic | 设计文件类数据 | 1 | 124 | 1134 | 0.6685 | 主类型命中：综合材料表 | `output/ocr/texts/IMG_6521.txt` |
| IMG_6522.heic | 设计文件类数据 | 1 | 111 | 986 | 0.6721 | 主类型命中：综合材料表 | `output/ocr/texts/IMG_6522.txt` |
| IMG_6523.heic | 设计文件类数据 | 1 | 85 | 706 | 0.6871 | 主类型命中：综合材料表 | `output/ocr/texts/IMG_6523.txt` |
| IMG_6524.heic | 图纸类数据 | 1 | 70 | 799 | 0.6071 | 主类型命中：配管平面图 | `output/ocr/texts/IMG_6524.txt` |
| IMG_6526.heic | 图纸类数据 | 1 | 7 | 47 | 0.3571 | 视觉抽检确认：低文本折叠图纸照片 | `output/ocr/texts/IMG_6526.txt` |
| IMG_6527.heic | 图纸类数据 | 1 | 5 | 16 | 0.4800 | 视觉抽检确认：低文本折叠图纸照片 | `output/ocr/texts/IMG_6527.txt` |
| IMG_6528.heic | 图纸类数据 | 1 | 5 | 22 | 0.3400 | 视觉抽检确认：低文本折叠图纸照片 | `output/ocr/texts/IMG_6528.txt` |
| IMG_6529.heic | 设计文件类数据 | 1 | 145 | 1015 | 0.4924 | 主类型命中：设备及管道油漆保温一览表 | `output/ocr/texts/IMG_6529.txt` |
| IMG_6530.heic | 设计文件类数据 | 1 | 240 | 1393 | 0.4650 | 主类型命中：管道特性表 | `output/ocr/texts/IMG_6530.txt` |

## OCR 文本摘录

### 20260623104523.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/ocr/texts/20260623104523.txt`

```text
中华人民共和国 特种设备安装改造维修许可证 Instaillation, Alteration, Repair &Maintenance License of Special Equipment People's Republic of China （压力管道） 编号：TS3810436-2021 单位名称：贵州化工建设有限责任公司 （原单位名称：贵州化工建...
```

### 20260623104555.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/ocr/texts/20260623104555.txt`

```text
===== page 1 ===== 副本 中华人民共和国 特种设备制造许可证 Manufacture License of Special Equipment People's Republic of China （压力管道元件） 编号：TS2710504-2022 单位名称：河北广浩管件有限公司 制造地址：河北省沧州市孟村回族自治县辛大公路肖庄子路段 经...
```

### 20260623104703.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/ocr/texts/20260623104703.txt`

```text
===== page 1 ===== 产品质量证明书 山东省烟台市福山区永达街1030号 NO.1030, YONGDA STREET,FUSHAN DISTRICT. YANTAI 宝⑥钢® 烟台魯宝钢管有限责任公司 INSPECTION CERTIFICATE 邮编：265500 SHANDONG:P.R.CHINA YANTAI LUBAO STEEL...
```

### 20260623104730.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/ocr/texts/20260623104730.txt`

```text
===== page 1 ===== 恒基达鑫一二期装车站 新增两套卸车系统项目压力管道安装 交工资料 施工单位：贵州化工建设有限责任公司 编制： 王蒸 审核： 日期：2021年4月10日 ===== page 2 ===== 目 录 1.压力管道安装质量证明书 ］ 附：压力管道汇总表 . 2 2.特种设备安装改造维修告知书 .3 附：业务办理资料接收回执....
```

### 20260623104828.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/ocr/texts/20260623104828.txt`

```text
===== page 1 ===== 河北广浩管件有限公司 产品出厂检验合格证 收货单位： 2021年3月18日 材质 20# 产品名称 规格 数量 执行标准 化学成分% 对焊法兰 WN100 （B） -16 RF S=5 14 HG/T20592-2009 碳C 锰 Mn 硅 Si 硫S 磷P 铬 Cr 镍 Ni 0.19 0.42 0.26 0.011 ...
```

### 20260623105454.pdf

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/20260623105454.txt`

```text
===== page 1 ===== 恒基达鑫一二期装车站新增两套卸车系统项目 ） 施工方案 施工单位：贵州化工建设有限责任公司 编制： 玉蒸 审核： 日期：2021年3月15日 ===== page 2 ===== 目 录 第一章 工程概况 。。1 1.工程概述⋯ ⋯.1 2. 工程范围及内容 ⋯..1 3.工期目标. ⋯1 4. 质量及安全目标. 1 第...
```

### 20260623105534.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/ocr/texts/20260623105534.txt`

```text
===== page 1 ===== 承压设备焊接工艺评定报告 编号： HP2013-10 单 位： 贵州化工建设公司 日 期 2013 年11月2日 ===== page 2 ===== 焊接位置： 对接㷆缝的位置 立悍的焊接方向：（向上、向下）_向下 5GX 焊后热处理； 角焊缝位置 保温温度（°C） 立 的焊接方向：（向上、向下） L 保温时间范围（h...
```

### 20260623105636.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/ocr/texts/20260623105636.txt`

```text
===== page 1 ===== 射线检测报告书 工程名称：恒基达鑫一二期装车站新增两套卸车系统项目 检件名称：压力管道 委托单位：贵州化工建设有限责任公司 报告编号：2021SHZH-014RTBG-01 广州声华科技股份有限公司 二零*年四月 1533520 ===== page 2 ===== SH/T 3503-J127-1 射线检测报告（主页）...
```

### IMG_6508.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6508.txt`

```text
a 广东星燃石化设计院有限公司 仅機 CHK 日E REU 管 道 装 材 料 表 图号 wK2019008-13-1-06 编号 起点 止点 压力 链儲成：$108x 名称 材料 名称 材料 SX 螺母 P1R303\| P8301A KF25-101-3.0 无隆销術中108x1 o.1 S0E（L） 100EI-Sch.40 E遊钢會 预侧135°鸾 1...
```

### IMG_6509.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6509.txt`

```text
GXPDI 广东星燃石化设计院有限公司 DUTY 职责 姓名 编制 NAME DATE 日期 UNIT NAME 装置名称 GUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE CO.LTD. PIPING CHARACTERISTIC LIST 管道特性表 卸车站 项目名称 即考主 2021.3 图纸编号 珠海恒...
```

### IMG_6510.heic

- 知识类型：图纸类数据
- OCR 文本：`output/ocr/texts/IMG_6510.txt`

```text
PL.882-100M1B100x80 ：100x80 P83OIA 四区交装站 化工品（两醇等） IN25 C R880-100MB 100x80 东省建设工程勘蔡设计出图专用章 图份， 菜闹 管道标注 截上网 香証书编号：A244010070 管道标注， 效期至：2024年6月21日 序号1，管道物料代号，RA-液体PS-气体 Mi-株漱 说期。 本圈纸...
```

### IMG_6511.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6511.txt`

```text
管道壁厚计算： 计算管道壁厚公式： 按20#（GB/T 8163-2018）无缝钢管参数计算，根据GB/T20801.3-2006《压力管道规范 工业管道》 1）当t＜D/6时，直管的计算厚度t=PD/（2 （S4+PY）） T=t+C；+C，+Cg+A （6.1节，公式（1），P26页） 序号 名称 2 计算厚度 名义厚度 代号 T 计算参数 备注 设计压...
```

### IMG_6512.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6512.txt`

```text
GXPDI 广东星燃石化设计院有限公司 职责 IUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE CI 项目名称 DUTY 姓名 日期 PROJECT 珠海恒基达鑫国际化工仓储股份 有限公司•一、二期装车站新增 两套卸车系统项目 DESIGN 编制 NAME DATE 装置名称 CHECK 校核 那募基 2021...
```

### IMG_6513.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6513.txt`

```text
编制 GXPDI 广东星燃石化 DES. P莠士2021.3 项目 珠海恒基达鑫国际化工仓储 图号 DWG.No. 股份有限公司 、 二期装 QX201903S-13-Y-03 设计院有限公司 校核 设备一览表 PROJ. 车站新增两套卸车系统项目 用户图号 CLIENT DWG.No. DESIGN INSTITUTE CO.LTD. GUANGDONG ...
```

### IMG_6514.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6514.txt`

```text
GXPDI 广东星燃石化设计院有限公司 DUTY 职贵 GUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE C（ PROJECT 项目名称 珠海恒基达鑫国际化工仓储股份有限公司• 编制 姓名 NAME 日期 二期装车站新增两套卸车系统项目 DESIGN 2021.3 DATE UNIT NAME 裝置名称 CHE...
```

### IMG_6515.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6515.txt`

```text
GXPDI 广东星燃石化设计院有限公司 项目名称 PROJECT 珠海恒基达鑫国际化工仓储股份 ONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE 有限公司•一、二期装车站新增 职贵 姓名 日期 装置名称 两套卸车系统项目 编制 DUTY NAME DATE UNIT NAME 卸车站 DESIGN 2021.3 工艺设计说...
```

### IMG_6516.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6516.txt`

```text
GXPDI 广东星燃石化设计院有限公司 DUTY 职责 GUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE C（ 项目名称 姓名 日期 PROIECT 珠海恒基达鑫国际化工仓储股份 有限公司•一、二期装车站新增 两套卸车系统项目 DESIGN 编制 NAME DATE 裝置名称 CHECK 校核 那喜或 2021...
```

### IMG_6517.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6517.txt`

```text
GXPDI 广东星燃石化设计院有限公司 职责 ANGDONG XINGRAN PETROCI MICAL DESIGN INSTITUTE C（ 项目名称 编制 DUTY NAME 姓名 DATE 日期 PROIECT 珠海恒基达鑫国际化工仓储股份 有限公司•一、二期装车站新增 裝置名称 两套卸车系统项目 DESIGN 那辦或 CHECK 校核 2021.3...
```

### IMG_6518.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6518.txt`

```text
GXPDI 广东星燃石化设计院有限公司 职责 GUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE C 项目名称 编制 DUTY NAME 姓名 DATE 日期 PROJECT 珠海恒基达鑫国际化工仓储股份 有限公司•一、二期装车站新增 裝置名称 两套卸车系统项目 DESIGN CHECK 校 核 別募或 2021...
```

### IMG_6519.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6519.txt`

```text
GXPDI 广东星燃石化设计院有限公司 GUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE CC 项目名称 职责 NAME 姓名 DATE 日期 PROJECT 珠海恒基达鑫国际化工仓储股份 有限公司•一、二期裝车站新增 DUTY 两套卸车系统项目 DESIGN 编制 装置名称 卸车站 CHECK 校核 2021...
```

### IMG_6520.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6520.txt`

```text
序号 PROJECT 项目名称 防爆电动球阀 止回阀 截止阀 截止阀 球阀 球阀 球阀 阀门 无缝钢管 无缝钢管 无缝钢管 无缝钢管 管子 Material Name & Specification 材料名称及规格 CUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE CO.LTD. 一厂东星燃仁化政计院有限公司 ...
```

### IMG_6521.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6521.txt`

```text
序号 PROJECT 项目名称 螺纹螺栓/II型六角螺 螺纹螺栓/II型六角螺 螺纹螺栓/II型六角螺 螺栓/螺母 缠绕垫 缠绕垫 缠绕垫 缠绕垫 垫片 法兰盖 法兰盖 带颈对㷆法兰 带颈对焊法兰 带颈对焊法兰 带颈对熚法兰 法兰 Material Name & Specification 材料名称及规格 GUANGDONG XINGRAN PETROCHE...
```

### IMG_6522.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6522.txt`

```text
序号 PROJECT 项目名称 压力表 Y型过滤器 防雨型防爆阻火器 复合软管 特殊件 丙烯酸聚酯面漆 环氧富锌防锈底漆 油漆，保温 偏心异径管 同心异径管 等径三通 135°无缝长半径弯头 90°无缝长半径弯头 90°无缝长半径弯头 管件 Materinl Name & Speciication 材料名称及规格 GUANGDONG XINGRAN PETR...
```

### IMG_6523.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6523.txt`

```text
序号 PROJECT 项目名称 镀锌扁钢 膨胀螺栓 U型管卡 钢板 角钢 槽钢 管架材料 MaterialName & opecucauon 材料名称及規格 GUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTTUTE CO.L TD. am广东星燃石化设计院有限公司 、二期装车站新增两套卸车系统项目 珠海恒基达鑫国际化工仓...
```

### IMG_6524.heic

- 知识类型：图纸类数据
- OCR 文本：`output/ocr/texts/IMG_6524.txt`

```text
压力管道 杨道红 东省建设工程勘察设计出图专用章 TS1810648-2021 二位名称在本星熊石化设计院有限公司 2017年8月31日 业务范围：凝运、主视、立豬芽、化羊麻辣味、他工全街）事五的 化工石化医药行业（中成药药物创剂、万油及化工产品 “黄征书编号：A244010070 效期至：2024年6月21日 本图纸为广东星燃石化没计院有限公司版权所有，未...
```

### IMG_6526.heic

- 知识类型：图纸类数据
- OCR 文本：`output/ocr/texts/IMG_6526.txt`

```text
4000m3 K404 装车站 消岗道路 監海消岗逍路 發系仪汞室 ，原星議在化後计採有限公司
```

### IMG_6527.heic

- 知识类型：图纸类数据
- OCR 文本：`output/ocr/texts/IMG_6527.txt`

```text
5000 因区袋 装车站 翻 •
```

### IMG_6528.heic

- 知识类型：图纸类数据
- OCR 文本：`output/ocr/texts/IMG_6528.txt`

```text
內洋 5000m3 中中中卯中 森区 • •
```

### IMG_6529.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6529.txt`

```text
广东星燃石化设计院有限公司 DUTY 职黃 NAME 姓名 GUANGDONG XINGRAN PE TROCHEMICAL DESIGN INSTITU TE CO.LTD EUIP： & PIPEPAINTINCand JNULATION LIST 设备及管道油漆保温一览表 日期 UNIT NAME 装置名称 闻车站 DESIGN 校核 孤意立 2021...
```

### IMG_6530.heic

- 知识类型：设计文件类数据
- OCR 文本：`output/ocr/texts/IMG_6530.txt`

```text
GXPDI 广东星燃石化设计院有限公司 GUANCDONG XINGRAN PE TROCHEMICAL DESICN INSTITUTE CO LTD. 管道特性表 姓名 DATE 日期 裝置名称 编制 20213 LNII NAME 卸牟站 项目名称 PIPING OFARACTDRISIICLIST DESIGN 朋嘉步 图纸编号 QX201903S-...
```
