"""FDE 治理总览首屏不该传 7 MB。

## 线上实测（2026-08-15，真实登录）

FDE 落地页 8 个请求、**6,971 KB**，两个接口占掉几乎全部：

    /fde/ocr-quality    6.9 秒   4,619 KB
    /fde/review-runs    6.6 秒   2,281 KB

拆开看：

- ocr-quality 里 parseResults 取了 20 条，每条平均 163 KB（fragments 最大 1.8 MB），
  而 `parseResults` 在前端**只出现在类型声明里**，没有任何视图读它；
- review-runs 里 atomicCheckToolBindingsSnapshot 每条 110 KB，一页 20 条正好 2.2 MB，
  前端对 atomicCheckToolBinding 的引用数是 **0**。

两处都是「传过去就被丢掉」。

## 判据

去掉内容，但留下计数和可追溯的标识——去掉了还看不出少了什么，才是真的坏。
"""

from __future__ import annotations

from apps.api.routes import fde_review_run_view, slim_ocr_parse_result


def test_解析结果去掉正文但留下计数():
    item = {
        "id": "OCR-1",
        "documentVersionId": "VER-1",
        "fragments": [{"text": "字" * 200} for _ in range(300)],
        "pages": [{"no": i} for i in range(40)],
        "tables": [{"rows": []}],
    }
    slimmed = slim_ocr_parse_result(item)
    assert "fragments" not in slimmed and "pages" not in slimmed
    assert slimmed["fragmentsCount"] == 300, "去掉了还看不出少了什么，等于把问题藏起来"
    assert slimmed["pagesCount"] == 40
    assert slimmed["tablesCount"] == 1
    assert slimmed["documentVersionId"] == "VER-1", "标识字段要留着"


def test_解析结果没有大块时原样返回():
    item = {"id": "OCR-2", "documentVersionId": "VER-2"}
    assert slim_ocr_parse_result(item) == item


def test_运行视图去掉绑定表快照但保留可追溯标识():
    run = {
        "reviewRunId": "RRUN-1",
        "id": "RRUN-1",
        "status": "completed",
        "atomicCheckToolBindingSetId": "bindings-v1",
        "atomicCheckToolBindingSetVersion": "2026.08.07",
        "atomicCheckToolBindingSetHash": "sha256:abc",
        "atomicCheckToolBindingSetLifecycle": "draft",
        "atomicCheckToolBindingsSnapshot": [{"atomicCheckId": f"AC-{i}"} for i in range(194)],
        "atomicCheckToolBindingSetSnapshot": {"atomicCheckCount": 194},
        "clausePackageSnapshot": {"clauses": ["x"] * 500},
        "findingDrafts": [],
    }
    view = fde_review_run_view(run)
    for bulky in (
        "atomicCheckToolBindingsSnapshot",
        "atomicCheckToolBindingSetSnapshot",
        "clausePackageSnapshot",
    ):
        assert bulky not in view, f"{bulky} 还在，一页 20 条就是几兆"
    # 追溯靠的是这几个，不能一起丢
    for kept in (
        "atomicCheckToolBindingSetId",
        "atomicCheckToolBindingSetVersion",
        "atomicCheckToolBindingSetHash",
        "atomicCheckToolBindingSetLifecycle",
    ):
        assert view.get(kept), f"{kept} 丢了，绑定表就追不回去了"


def test_两个列表视图都处理了():
    """ai_run 与 review_run 是同一个形状，只修一边等于没修。"""
    import inspect

    from apps.api import routes

    for name in ("fde_ai_run_view", "fde_review_run_view"):
        source = inspect.getsource(getattr(routes, name))
        assert "atomicCheckToolBindingsSnapshot" in source, f"{name} 没剥掉绑定表快照"
