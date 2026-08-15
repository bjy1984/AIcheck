"""MinerU 取源文件时，必须认得桶相对键。

## 线上实测（2026-08-15）

施工方传上一份真实许可证 PDF，走完上传三步都正常（PUT 200、完成 200、
任务派发到 ocr.remote），4 秒后失败：

    MINERU_SOURCE_MISSING  stage=upload

文件明明在 MinIO 里躺着。原因是 `mineru_source_path` 只走
`parse_storage_url`，而那个函数只认 `minio://bucket/key`；上传会话落库的是
`documents/P-2026-.../DV-...-V1` 这种**桶相对键**，桶名单独存在版本记录里。
解析不出来就退到「本地文件系统找找看」，自然找不到。

同一个文件里 `ocr_pipeline_source_path` 早就做了桶回退——两条取文件的路径
口径不一致，其中一条错了三个月没人发现，因为错的那条的症状是
「资料一直没识别出来」，看起来像模型不行，不像配置不通。

## 判据

给一个只有桶相对键的 job，必须去对象存储里取；桶名从 job 的 storageBucket
读，缺省 documents。
"""

from __future__ import annotations

from pathlib import Path

from apps.worker import tasks


def test_桶相对键要去对象存储取(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []
    target = tmp_path / "source.pdf"
    target.write_bytes(b"%PDF-1.4\n")

    def fake_download(bucket, object_name, *, suffix=""):
        calls.append((bucket, object_name))
        return target

    monkeypatch.setattr(tasks.object_storage, "download_to_temp", fake_download)

    path, root = tasks.mineru_source_path(
        {
            "storageKey": "documents/P-2026-5981A3/DV-52043DB1-V1",
            "storageBucket": "documents",
            "fileName": "许可证.pdf",
        }
    )

    assert calls == [("documents", "documents/P-2026-5981A3/DV-52043DB1-V1")]
    assert path == target
    assert root == target.parent


def test_没写桶名时默认documents(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []
    target = tmp_path / "source.pdf"
    target.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        tasks.object_storage,
        "download_to_temp",
        lambda bucket, object_name, *, suffix="": (calls.append((bucket, object_name)), target)[1],
    )

    tasks.mineru_source_path(
        {"storageKey": "documents/P/DV-1", "fileName": "a.pdf"}
    )

    assert calls == [("documents", "documents/P/DV-1")]


def test_minio_协议键仍走原路径(monkeypatch, tmp_path):
    """回退不能把原来能用的那条改坏。"""
    calls: list[tuple[str, str]] = []
    target = tmp_path / "s.pdf"
    target.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        tasks.object_storage,
        "download_to_temp",
        lambda bucket, object_name, *, suffix="": (calls.append((bucket, object_name)), target)[1],
    )

    tasks.mineru_source_path(
        {"storageKey": "minio://documents/P/DV-9", "fileName": "b.pdf"}
    )

    assert calls == [("documents", "P/DV-9")]


def test_任务记录带上桶名():
    """job 记录里没有 storageBucket，worker 就没法拼回对象地址。"""
    from libs.db.repository import repo

    job = repo.create_ocr_job_record(
        document_id="DOC-T1",
        version_id="DV-T1-V1",
        storage_key="documents/P-T/DV-T1-V1",
        storage_bucket="documents",
        file_name="t.pdf",
    )
    assert job["storageBucket"] == "documents"
    assert Path(job["storageKey"]).name == "DV-T1-V1"
