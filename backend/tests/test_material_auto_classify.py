"""上传后自动识别类别（0817 第 2 条）。

    「不需要资料对应上传，直接资料上传后自动识别类别，
      提示缺的内容以及未通过的部分」

把分类从「用户的输入」变成「系统的输出」。

## 三条判据

1. **最长命中取胜**。「制造单位许可证」比「许可证」具体。
   前端那份分类器就是栽在「首个匹配即胜」上（0817 第 1 条）。
2. **拿不准返回 None**，不猜。猜错的类别会让规则去错的地方取证，
   最后表现为「资料传了却判缺项」——而界面上分对和分错长得一模一样。
3. **不覆盖人选的类别**。人选过的就是人说了算。
"""

from __future__ import annotations

from libs.db.repository import InMemoryRepository
from libs.material_auto_classify import classify_material


def test_识别元件制造许可证():
    """现实里的文件名不会照抄审查点的名字。

    审查点叫「制造单位许可证」，证书封面和文件名写的是「特种设备生产许可证」。
    只按审查点名字匹配的话，**最常见的几种证照一个都认不出来**。
    要验的是归到哪一类、对应哪个编码，不是显示名长什么样。
    """
    result = classify_material(file_name="特种设备生产许可证-贵州化工.pdf")
    assert result, "最常见的证照文件名认不出来"
    assert result["materialTypeCode"] == "manufacturing_license"
    # 第 1 条修过：元件制造许可证属于材料，不是资质证照
    assert result["materialCategory"] == "材料验收与复验"
    assert result["matchedBy"] == "fileName"


def test_设计资质归到资质证照():
    """别名不能把整类都推到材料侧去。"""
    result = classify_material(file_name="特种设备设计资质.png")
    assert result
    assert result["materialTypeCode"] == "design_license"
    assert result["materialCategory"] == "资质证照"


def test_别名的类别取自配置而不是写死():
    """别名只补名字。类别写死在这里的话，就成了第二份分类定义，
    迟早和 material_review_points.json 漂移。"""
    from libs.material_auto_classify import ALIASES, _dictionary

    by_code = {code: category for _, category, code in _dictionary()}
    for alias, code in ALIASES.items():
        hit = classify_material(file_name=f"{alias}.pdf")
        if hit is None:  # 配置里没有这个 code，别名被丢弃是对的
            assert code not in by_code, f"{alias} 对应的 {code} 在配置里存在，却没认出来"
            continue
        assert hit["materialCategory"] == by_code[code], f"{alias} 的类别和配置对不上"


def test_最长命中取胜():
    """同时含「材料复验报告」和「报告」时，取更具体的那个。"""
    result = classify_material(file_name="材料复验报告-20260817.pdf")
    assert result
    assert result["materialTypeName"] == "材料复验报告"
    assert result["materialCategory"] == "材料验收与复验"


def test_分隔符不影响命中():
    """「特种设备_生产-许可证（正本）.pdf」也要能认出来。"""
    assert classify_material(file_name="材料-复验_报告（正本）.pdf")


def test_没有任何分类信号时统一进入未分类资料():
    """零信号不能返回空值，否则后续切片无法形成稳定的未分类检索池。"""
    for result in (
        classify_material(file_name="扫描件001.pdf"),
        classify_material(file_name=""),
        classify_material(),
    ):
        assert result["materialCategory"] == "未分类资料"
        assert result["materialTypeCode"] == "unclassified_material"
        assert result["materialTypeName"] == "未分类资料"
        assert result["classificationStatus"] == "unclassified"
        assert result["classificationConfidence"] == 0.0


def test_文件名优先于正文():
    """正文里出现「制造许可证」可能只是引用了一句法规。"""
    result = classify_material(
        file_name="材料复验报告.pdf",
        ocr_text="依据 TSG 规定，需核对制造单位许可证……",
    )
    assert result["materialTypeName"] == "材料复验报告"
    assert result["matchedBy"] == "fileName"


def test_文件名认不出时才用正文并标出来源():
    result = classify_material(file_name="scan001.pdf", ocr_text="本页为材料复验报告")
    assert result
    assert result["matchedBy"] == "ocrText"


def test_任何非零分类信号都产生正式分类结果():
    result = classify_material(file_name="scan001.pdf", ocr_text="本页为材料复验报告")

    assert result["materialTypeCode"] == "material_retest_report"
    assert result["classificationStatus"] == "classified"
    assert result["classificationConfidence"] > 0
    assert result["classificationSource"] == "ocr_classifier"
    assert result["classifierVersion"]


def test_document_type精确提示优先于较弱的文件名和正文信号():
    result = classify_material(
        file_name="材料复验报告.pdf",
        ocr_text="材料复验报告",
        document_type="design_license",
    )

    assert result["materialTypeCode"] == "design_license"
    assert result["matchedBy"] == "documentType"
    assert result["classificationConfidence"] == 1.0


def test_profile提示能够映射到标准资料类型():
    result = classify_material(
        file_name="scan001.pdf",
        profile_id="quality_certificate_v1",
    )

    assert result["materialTypeCode"] == "quality_certificate"
    assert result["matchedBy"] == "profileId"
    assert result["classificationConfidence"] > 0


def test_给出依据():
    """只给结论不给依据的话，用户发现分错了也不知道该改什么。"""
    result = classify_material(file_name="材料复验报告.pdf")
    assert "材料复验报告" in result["reason"]
    assert "文件名" in result["reason"]


def test_不覆盖人选的类别():
    """人选过的就是人说了算。"""
    repo = InMemoryRepository()
    doc, _ = repo.create_document(
        "P-2026-HDCP-001",
        "材料复验报告.pdf",
        "application/pdf",
        material_category="设计资料",
    )
    assert doc["materialCategory"] == "设计资料"
    assert "autoClassification" not in doc


def test_没选类别时自动填并留下建议来源():
    repo = InMemoryRepository()
    doc, _ = repo.create_document(
        "P-2026-HDCP-001", "材料复验报告.pdf", "application/pdf"
    )
    assert doc["materialCategory"] == "材料验收与复验"
    # 「系统猜的」和「人定的」要分得开，否则之后谁也说不清哪个是哪个
    assert doc["autoClassification"]["matchedBy"] == "fileName"
    assert doc["autoClassification"]["materialTypeName"] == "材料复验报告"


def test_认不出来时写入统一未分类结果而不是猜测具体类别():
    repo = InMemoryRepository()
    doc, _ = repo.create_document("P-2026-HDCP-001", "扫描件001.pdf", "application/pdf")
    assert doc["materialCategory"] == "未分类资料"
    assert doc["materialTypeCode"] == "unclassified_material"
    assert doc["autoClassification"]["classificationConfidence"] == 0.0
