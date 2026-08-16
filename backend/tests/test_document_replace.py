"""替换资料 = 在原文档上加版本，不是删掉重传。

## 来源

施工方反馈：上传成功后看不到已传资料，也没有预览／替换／删除。
预览和删除本来就有，**替换整个不存在**——上传永远新建文档。

## 为什么不能用「删掉重传」凑合

删掉重传会换一个新的 documentId，于是：
- 节点挂接断了（原来挂在哪个审查点，要重挂一次）；
- 审查意见里引用的证据指向一份已经不存在的资料；
- 监检看到的是「原来那份没了，多了一份陌生的」，无从判断是不是同一件事。

同一个文档下加版本，历史留痕、引用不断。

## 一条硬约束

**已提交/已审批的资料不允许直接替换。** 那份文件此刻可能正被监检看着、
已经写进审查意见的证据链。在审查员眼皮底下换掉证据，比不让替换危险得多——
要改就走补正流程，留下痕迹。
"""

from __future__ import annotations

import pytest

from libs.db.repository import repo


def _make_document(project_id: str = "P-REPLACE", status: str = "已上传") -> dict:
    session_id, urls = repo.create_upload_session(
        project_id,
        [{"fileName": "质量证明.pdf", "fileType": "pdf", "fileSize": 1024}],
    )
    document_id = urls[0]["documentId"]
    document = repo.find_one("documents", document_id)
    document["fileStatus"] = status
    return document


@pytest.fixture(autouse=True)
def _project():
    repo.state.setdefault("projects", [])
    if not repo.find_one("projects", "P-REPLACE"):
        repo.state["projects"].insert(
            0, {"id": "P-REPLACE", "name": "替换测试项目", "contractorOrgName": "施工测试"}
        )
    yield


def test_替换在原文档上加版本():
    document = _make_document()
    document_id = document["id"]
    before = len(repo.state["documents"])

    repo.create_upload_session(
        "P-REPLACE",
        [
            {
                "fileName": "质量证明-修订.pdf",
                "fileType": "pdf",
                "fileSize": 2048,
                "replaceDocumentId": document_id,
            }
        ],
    )

    assert len(repo.state["documents"]) == before, "替换不该新建文档——新建就等于挂接和证据全断了"
    versions = repo.versions_for_document(document_id)
    assert len(versions) == 2
    assert [item["versionNo"] for item in versions] == ["V1", "V2"] or sorted(
        item["versionNo"] for item in versions
    ) == ["V1", "V2"]


def test_旧版本让位为历史():
    document = _make_document()
    document_id = document["id"]
    repo.create_upload_session(
        "P-REPLACE",
        [{"fileName": "新版.pdf", "fileType": "pdf", "fileSize": 99, "replaceDocumentId": document_id}],
    )
    versions = repo.versions_for_document(document_id)
    current = [item for item in versions if item.get("isCurrent")]
    assert len(current) == 1, "同一时刻只能有一个当前版本"
    assert current[0]["versionNo"] == "V2"
    old = next(item for item in versions if item["versionNo"] == "V1")
    assert old.get("replacedAt"), "旧版本要留下被替换的时间，否则看不出发生过替换"


def test_文档指向新版本并重新排队识别():
    document = _make_document()
    document_id = document["id"]
    repo.create_upload_session(
        "P-REPLACE",
        [{"fileName": "新版.pdf", "fileType": "pdf", "fileSize": 99, "replaceDocumentId": document_id}],
    )
    updated = repo.find_one("documents", document_id)
    assert updated["currentVersionId"].endswith("-V2")
    assert updated["currentOcrStatus"] == "排队中", "换了文件就要重新识别，沿用旧结果等于认了旧内容"


def test_替换不存在的资料要报错():
    with pytest.raises(ValueError, match="要替换的资料不存在"):
        repo.create_upload_session(
            "P-REPLACE",
            [{"fileName": "x.pdf", "fileType": "pdf", "replaceDocumentId": "DOC-NOT-EXIST"}],
        )


def test_跨项目替换要报错():
    """A 项目的人不能用替换这条路去改 B 项目的资料。"""
    document = _make_document()
    repo.state["projects"].insert(0, {"id": "P-OTHER", "name": "另一个项目"})
    with pytest.raises(ValueError):
        repo.create_upload_session(
            "P-OTHER",
            [{"fileName": "x.pdf", "fileType": "pdf", "replaceDocumentId": document["id"]}],
        )


def test_路由层拦住已提交资料():
    """已提交的资料正被监检看着，替换要走补正流程。"""
    import inspect

    from apps.api import routes

    source = inspect.getsource(routes.validate_replace_targets)
    assert '"草稿", "已上传"' in source, "只有未提交状态可替换"
    assert "补正流程" in source, "要说清楚该走哪条路，而不是只说不行"


def test_落库范围要覆盖被顶下去的旧版本():
    """线上实测抓到、而单测没抓住的那一条。

    替换成功、V2 建出来了，文档却仍指向 V1，两条版本都写着「当前」——
    因为落库只写本次会话的 version_id，被顶成历史的 V1 不在其中，
    它的 isCurrent=false 只改在内存里，没写回数据库。

    **内存里改对了、没写回去，和没改一样**，而且更难查：
    单测直接操作内存，一路全绿。所以这条按「落库范围」来断言。
    """
    import inspect

    from apps.api import routes

    source = inspect.getsource(routes.upload_session_state_records)
    assert 'str(item.get("documentId") or "") in document_ids' in source, (
        "versions 要按文档取全部版本，否则被替换掉的旧版本不会落库"
    )


def test_每个版本记住自己的文件名():
    """替换之后文档名不变（标识要稳），但要看得出这一版换进去的是哪个文件。

    **换对了没有，是替换这个动作的全部意义**——界面上只显示原文档名，
    用户没有任何办法确认自己刚才传的是不是想传的那份。
    """
    document = _make_document()
    document_id = document["id"]
    repo.create_upload_session(
        "P-REPLACE",
        [
            {
                "fileName": "质量证明-第二版.pdf",
                "fileType": "pdf",
                "fileSize": 4096,
                "replaceDocumentId": document_id,
            }
        ],
    )
    versions = {item["versionNo"]: item for item in repo.versions_for_document(document_id)}
    assert versions["V1"]["fileName"] == "质量证明.pdf", "第一版也要记，否则历史里 V1 是空的"
    assert versions["V2"]["fileName"] == "质量证明-第二版.pdf"
    # 文档名不跟着变：它是这份资料的标识，跟着每次替换改会让引用它的地方对不上
    assert repo.find_one("documents", document_id)["fileName"] == "质量证明.pdf"
