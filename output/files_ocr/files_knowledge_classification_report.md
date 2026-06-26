# files 知识类型分类与 OCR 结果

- 处理时间：2026-06-24
- 分类依据：`knowledge_governance_tooling_plan.md` 中的五类知识来源：图纸、设计文件、现场照片、证书 OCR、标准规范。
- 提取方法：PDF 优先抽文本层，文本层为空或低信号页用 Poppler 渲染后走 macOS Vision 中英文 OCR；图片直接用 Vision OCR。
- 输出文本目录：`output/files_ocr/texts/`
- 逐行溯源记录：`output/files_ocr/ocr_records.jsonl`
- 分类表：`output/files_ocr/classification.csv`

## 提取方法汇总

| 方法 | 行数 |
|---|---:|
| macos_vision_ocr_v1 | 43207 |
| pdf_text_layer_v1 | 8459 |

## 分类汇总

| 知识类型 | 文件数 | 页/图数 | OCR 行数 | 平均置信度 |
|---|---:|---:|---:|---:|
| 图纸类数据 | 0 | 0 | 0 | 0.0000 |
| 设计文件类数据 | 1 | 10 | 1012 | 0.7085 |
| 现场照片类数据 | 0 | 0 | 0 | 0.0000 |
| 证书 OCR 类数据 | 3 | 37 | 2997 | 0.5788 |
| 标准规范类数据 | 14 | 936 | 47657 | 0.7074 |
| 待人工复核 | 0 | 0 | 0 | 0.0000 |

## 文件级结果

| 文件 | 知识类型 | 页/图数 | OCR 行数 | 字符数 | 平均置信度 | 分类证据 | OCR 文本 |
|---|---|---:|---:|---:|---:|---|---|
| 21fe60f0448d3fe8db68be35e811c560.jpg | 标准规范类数据 | 1 | 59 | 885 | 0.6864 | 视觉抽检确认：特种设备许可目录页 | `output/files_ocr/texts/21fe60f0448d3fe8db68be35e811c560.txt` |
| GB 50235-2010 工业金属管道工程施工规范.pdf | 标准规范类数据 | 129 | 7354 | 120211 | 0.6510 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB 50235-2010 工业金属管道工程施工规范.txt` |
| GB 50236-2011 现场设备、工业管道焊接工程施工规范.pdf | 标准规范类数据 | 132 | 4414 | 72939 | 0.5573 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB 50236-2011 现场设备、工业管道焊接工程施工规范.txt` |
| GBT 8163-2018 输送流体用无缝钢管.pdf | 标准规范类数据 | 21 | 1240 | 19122 | 1.0000 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GBT 8163-2018 输送流体用无缝钢管.txt` |
| GB∕T 20801.1-2020 压力管道规范 工业管道 第1部分：总则.pdf | 标准规范类数据 | 8 | 283 | 5996 | 0.5647 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB∕T 20801.1-2020 压力管道规范 工业管道 第1部分：总则.txt` |
| GB∕T 20801.2-2020 压力管道规范 工业管道 第2部分：材料.pdf | 标准规范类数据 | 89 | 8941 | 102532 | 0.6305 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB∕T 20801.2-2020 压力管道规范 工业管道 第2部分：材料.txt` |
| GB∕T 20801.3-2020 压力管道规范 工业管道 第3部分：设计和计算.pdf | 标准规范类数据 | 98 | 5146 | 88588 | 0.6007 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB∕T 20801.3-2020 压力管道规范 工业管道 第3部分：设计和计算.txt` |
| GB∕T 20801.4-2020 压力管道规范 工业管道 第4部分：制作与安装.pdf | 标准规范类数据 | 44 | 2872 | 41737 | 0.7049 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB∕T 20801.4-2020 压力管道规范 工业管道 第4部分：制作与安装.txt` |
| GB∕T 20801.5-2020 压力管道规范 工业管道 第5部分：检验与试验.pdf | 标准规范类数据 | 17 | 852 | 15857 | 0.6556 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB∕T 20801.5-2020 压力管道规范 工业管道 第5部分：检验与试验.txt` |
| GB∕T 20801.6-2020 压力管道规范 工业管道 第6部分：安全防护.pdf | 标准规范类数据 | 31 | 1790 | 25717 | 0.6402 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/GB∕T 20801.6-2020 压力管道规范 工业管道 第6部分：安全防护.txt` |
| NBT47014承压设备焊接工艺评定.pdf | 标准规范类数据 | 88 | 4297 | 58418 | 0.6035 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/NBT47014承压设备焊接工艺评定.txt` |
| TSG D7006-2020 压力管道监督检验规则.pdf | 标准规范类数据 | 41 | 1184 | 30011 | 1.0000 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/TSG D7006-2020 压力管道监督检验规则.txt` |
| TSGZ6002-2010《焊接人员考核细则》.pdf | 标准规范类数据 | 64 | 3154 | 38321 | 0.6107 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/TSGZ6002-2010《焊接人员考核细则》.txt` |
| 交工资料.pdf | 证书 OCR 类数据 | 24 | 2254 | 13317 | 0.7190 | 主类型命中：交工/质量证明资料 | `output/files_ocr/texts/交工资料.txt` |
| 材质证书.pdf | 证书 OCR 类数据 | 7 | 549 | 5939 | 0.4446 | 主类型命中：质量证明书 | `output/files_ocr/texts/材质证书.txt` |
| 特种设备生产和充装单位许可规则TSG 07-2019.pdf | 标准规范类数据 | 173 | 6071 | 142504 | 0.9980 | 文件名命中：标准/规范编号 | `output/files_ocr/texts/特种设备生产和充装单位许可规则TSG 07-2019.txt` |
| 设计资料.pdf | 设计文件类数据 | 10 | 1012 | 9843 | 0.7085 | 主类型命中：工艺设计说明书 | `output/files_ocr/texts/设计资料.txt` |
| 资质证书.pdf | 证书 OCR 类数据 | 6 | 194 | 2232 | 0.5727 | 主类型命中：特种设备安装改造维修许可证 | `output/files_ocr/texts/资质证书.txt` |

## OCR 文本摘录

### 21fe60f0448d3fe8db68be35e811c560.jpg

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/21fe60f0448d3fe8db68be35e811c560.txt`

```text
特种设备生产单位许可目录 许可级剔 注一：压力管道设计、安装许可参数级别 许可范围 GAI 长输输气管道 1.设计压力大于或者等于4.0MPa（表压，下同）的 备注 GB1 GA2 GA1 级以外的长输管道 2.设计压力大于或者等于6.3MPa 的长输输油管道 GA1 級覆盖 GA2级 GB2 燃气管道 1.输送《危险化学品目录》中规定的毒性程度为急性 热力...
```

### GB 50235-2010 工业金属管道工程施工规范.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB 50235-2010 工业金属管道工程施工规范.txt`

```text
===== page 1 ===== UDC 中华人民共和国国家标准 qE P GB 50235 -2010 工业金属管道工程施工规范 Code for construction of industrial metallic piping engineering 2010-08-18 发布 2011-06-01 实施 中华人民共和国住房和城乡建设部 中华人民...
```

### GB 50236-2011 现场设备、工业管道焊接工程施工规范.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB 50236-2011 现场设备、工业管道焊接工程施工规范.txt`

```text
===== page 1 ===== 中华人民共和国国家标准 现场设备、工业管道焊接工程施工规范 Code for construction of ficld equipment， industrial pipe welding engineering GB 50236-2011 主编部门：中国工程建设标准化协会化工分会 批准部门：中华人民共和国住房和城乡建...
```

### GBT 8163-2018 输送流体用无缝钢管.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GBT 8163-2018 输送流体用无缝钢管.txt`

```text
===== page 1 ===== ICs 77 14075 H 48 中 华 人 民 共 和 国 国 家 标 准 GB/T8163-2018 代 替 GB/T8163-2oo8 输送流体 用无缝钢 管 sea1nless steeI pipes for Iiquid service 2018-0⒌14发布 逞鼍鼍廴 篾 黼 愿 蚋 聱 垦 发 布 201...
```

### GB∕T 20801.1-2020 压力管道规范 工业管道 第1部分：总则.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB∕T 20801.1-2020 压力管道规范 工业管道 第1部分：总则.txt`

```text
===== page 1 ===== ICS 23.040 J 74 GB 中华人民共和国国家标准 GB/T 20801.1—2020 代替 GB/T 20801.1 -2006 压力管道规范 工业管道 第1部分：总则 Pressure piping code—Industrial piping—Part 1:General 2020-03-06 发布 20...
```

### GB∕T 20801.2-2020 压力管道规范 工业管道 第2部分：材料.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB∕T 20801.2-2020 压力管道规范 工业管道 第2部分：材料.txt`

```text
===== page 1 ===== ICS 23.040 J 74 GB 中华人民共和国国家标准 GB/T 20801.2—2020 代替 GB/T 20801.2 -2006 压力管道规范 工业管道 第2部分：材料 Pressure piping code—Industrial piping—Part 2:Materials 2020-11-19发布 2...
```

### GB∕T 20801.3-2020 压力管道规范 工业管道 第3部分：设计和计算.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB∕T 20801.3-2020 压力管道规范 工业管道 第3部分：设计和计算.txt`

```text
===== page 1 ===== ICS 23.040 J 74 GB 中华人民共和国国家标准 GB/T 20801.3—2020 代替 GB/T 20801.3 -2006 压力管道规范 工业管道 第3部分：设计和计算 Pressure piping code—Industrial piping—Part 3:Design and calculatio...
```

### GB∕T 20801.4-2020 压力管道规范 工业管道 第4部分：制作与安装.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB∕T 20801.4-2020 压力管道规范 工业管道 第4部分：制作与安装.txt`

```text
===== page 1 ===== ICS 23.040 J 74 GB 中华人民共和国国家标准 GB/T 20801.4—2020 代替 GB/T 20801.4 —2006 压力管道规范 工业管道 第4部分：制作与安装 Pressure piping code—Industrial piping—Part 4:Fabrication and assem...
```

### GB∕T 20801.5-2020 压力管道规范 工业管道 第5部分：检验与试验.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB∕T 20801.5-2020 压力管道规范 工业管道 第5部分：检验与试验.txt`

```text
===== page 1 ===== ICS 23.040 J 74 GB 中华人民共和国国家标准 GB/T 20801.5—2020 代替 GB/T 20801.5 -2006 压力管道规范 工业管道 第5部分：检验与试验 Pressure piping code—Industrial piping—Part 5:Inspection and testin...
```

### GB∕T 20801.6-2020 压力管道规范 工业管道 第6部分：安全防护.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/GB∕T 20801.6-2020 压力管道规范 工业管道 第6部分：安全防护.txt`

```text
===== page 1 ===== ICS 23.040 J 74 GB 中华人民共和国国家标准 GB/T 20801.6—2020 代替 GB/T 20801.6 -2006 压力管道规范 工业管道 第6部分：安全防护 Pressure piping code—Industrial piping—Part 6: Safeguarding 2020-11-...
```

### NBT47014承压设备焊接工艺评定.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/NBT47014承压设备焊接工艺评定.txt`

```text
===== page 1 ===== NB/T 47014-2011《承压设备焊接工艺评定》 勘误表 序 号 标准代号及页次 条款 原文 修改为 1 NB/T 47014（P.22） 表3（续）第6行右端 ER55-C3 ERSS-Ni3 2 NB/T 47014 （P.37） 表7第1行右侧 ⋯⋯焊缝金属厚度（t） 的⋯… ⋯•⋯•焊缝金属厚度的•• 3 ...
```

### TSG D7006-2020 压力管道监督检验规则.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/TSG D7006-2020 压力管道监督检验规则.txt`

```text
===== page 1 ===== TSG特种设备安全技术规范 TSG D7006—2020 压力管道监督检验规则 Pressure Pipe Supervision Inspection Regulation 国家市场监督管理总局颁布 2020年5月16日 ===== page 2 ===== 特种设备安全技术规范 TSG D7006—2020 前 言 ...
```

### TSGZ6002-2010《焊接人员考核细则》.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/TSGZ6002-2010《焊接人员考核细则》.txt`

```text
===== page 1 ===== TSG 特种设备安金技术规苑 TSG Z6002-2010 特种设备焊接操作人员考核细则 Examination Rules for Welding Operators of Special Equipment 中华人民共和国国家质量监督检验检疫总局颁布 2010年11月4日 ===== page 2 ===== TSG...
```

### 交工资料.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/files_ocr/texts/交工资料.txt`

```text
===== page 1 ===== 恒基达鑫一二期装车站 新增两套卸车系统项目压力管道安装 交工资料 施工单位：贵州化工建设有限责任公司 编制： 王巫 审核： 日期：2021年4月10日 ===== page 2 ===== 目 录 1.压力管道安装质量证明书 附：压力管道汇总表 2 2.特种设备安装改造维修告知书 3 附：业务办理资料接收回执. 5 3....
```

### 材质证书.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/files_ocr/texts/材质证书.txt`

```text
===== page 1 ===== 嚴务热线 400-820-8590 021-26648888 BGSQG1910220001600 沈绍陆 PAGE 1 OF 3 G9K6920545 NO.1030. YONGDA STREET,FUSHAN DISTRICT,YANTAI 2020~12-05 山东省烟台市福山区永达街1030号 TEL:0535-...
```

### 特种设备生产和充装单位许可规则TSG 07-2019.pdf

- 知识类型：标准规范类数据
- OCR 文本：`output/files_ocr/texts/特种设备生产和充装单位许可规则TSG 07-2019.txt`

```text
===== page 1 ===== TSG 特种设备安全技术规范 TSG 07—2019 国家市场监督管理总局颁布 2019 年 5 月 13 日 特种设备生产和充装单位 许可规则 Regulation for Production an d Filling Licensing of Special Equipment ===== page 2 =====...
```

### 设计资料.pdf

- 知识类型：设计文件类数据
- OCR 文本：`output/files_ocr/texts/设计资料.txt`

```text
===== page 1 ===== GXPDI 广东星燃石化设计院有限公司 PROJECT 项目名称 珠海恒基达鑫国际化工仓储股份有限公司•一、 职责 GUANGDONG XINGRAN PETROCHEMICAL DESIGN INSTITUTE CO 二期装车站新增两套卸车系统项目 DUTY 姓名 NAME 日期 编制 DATE UNIT NAME 裝...
```

### 资质证书.pdf

- 知识类型：证书 OCR 类数据
- OCR 文本：`output/files_ocr/texts/资质证书.txt`

```text
===== page 1 ===== GC1 级 GB2（2）级 GB1（含PE专项）、 GA1 乙级 级别 有效期至：2021年4月27日 审批机关：国家质量监督检验检疫总局 单位地址：贵州省贵阳市乌当区洛湾 （原单位名称：贵州化工建设公司） 单位名称：贵州化工建设有限责任公司 050印巴 经审查，获准从事下列压力管道的安装： 工业管道 公用管道 长输管道...
```
