#!/usr/bin/env python3
"""用 MinerU 重跑标准库文件，保留 full.md + content_list/layout sidecar，支持断点续跑。

默认输入源：output/knowledge_uploads/KS-STANDARD-RULES/{knowledgeFileId}/
（与 knowledgeFileId 一一对应，不靠文件名模糊匹配）

产物目录默认：rules/results/mineru_sidecar/{knowledgeFileId}/
  - full.md
  - content_list.json（若 zip 内有）
  - layout.json（若 zip 内有）
  - full.zip（可选，--keep-zip）
  - meta.json

断点文件：rules/results/mineru_sidecar/_checkpoint.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
UPLOADS_DEFAULT = ROOT / "output" / "knowledge_uploads" / "KS-STANDARD-RULES"
OUTPUT_DEFAULT = ROOT / "rules" / "results" / "mineru_sidecar"
LEGACY_MD_DEFAULT = ROOT / "rules" / "results"
BASELINE_FILES = BACKEND / "data" / "standards_mineru_baseline" / "files.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from libs.integrations.mineru_client import (  # noqa: E402
    MinerUClient,
    MinerUError,
    MinerUJobFailed,
    MinerUProtocolError,
    load_mineru_config,
)

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".heic", ".heif", ".tiff", ".txt", ".md"}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uploads-root", default=str(UPLOADS_DEFAULT))
    parser.add_argument("--output-dir", default=str(OUTPUT_DEFAULT))
    parser.add_argument("--legacy-md-dir", default=str(LEGACY_MD_DEFAULT), help="兼容旧的 rules/results/*.md 写出位置")
    parser.add_argument(
        "--baseline-files",
        default=str(BASELINE_FILES),
        help="默认只处理基线里的标准库 knowledgeFileId，避免把 uploads 历史目录全跑一遍",
    )
    parser.add_argument(
        "--all-uploads",
        action="store_true",
        help="处理 uploads 下全部目录（危险：含历史重复 KF）",
    )
    parser.add_argument("--language", default="ch")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--keep-zip", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--file-id", action="append", default=[], help="只处理指定 knowledgeFileId，可重复")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-checkpoint", action="store_true")
    return parser.parse_args()


def _safe_decode(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _active_file_ids(baseline_files: Path) -> list[str]:
    if not baseline_files.exists():
        raise RuntimeError(
            f"缺少基线文件 {baseline_files}；请先运行 standards_mineru_baseline.py freeze，"
            "或改用 --file-id / --all-uploads"
        )
    rows = json.loads(baseline_files.read_text(encoding="utf-8"))
    return [str(item["knowledgeFileId"]) for item in rows if item.get("knowledgeFileId")]


def _discover_uploads(uploads_root: Path, file_ids: list[str]) -> list[tuple[str, Path]]:
    if not uploads_root.is_dir():
        raise RuntimeError(f"uploads 目录不存在: {uploads_root}")
    selected = set(file_ids)
    items: list[tuple[str, Path]] = []
    missing: list[str] = []
    for knowledge_file_id in sorted(selected):
        directory = uploads_root / knowledge_file_id
        if not directory.is_dir():
            missing.append(knowledge_file_id)
            continue
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ]
        if not candidates:
            missing.append(knowledge_file_id)
            continue
        source = sorted(candidates, key=lambda item: (-item.stat().st_size, item.name))[0]
        items.append((knowledge_file_id, source))
    if missing:
        print(f"warning: {len(missing)} active files missing uploads: {', '.join(missing[:8])}")
    return items


def _discover_all_uploads(uploads_root: Path) -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    for directory in sorted(path for path in uploads_root.iterdir() if path.is_dir()):
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ]
        if not candidates:
            continue
        source = sorted(candidates, key=lambda item: (-item.stat().st_size, item.name))[0]
        items.append((directory.name, source))
    return items


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"completed": {}, "failed": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _extract_sidecar(zip_data: bytes) -> dict[str, Any]:
    artifact_names: list[str] = []
    markdown_text = ""
    content_list_raw: bytes | None = None
    content_list_name = ""
    layout_raw: bytes | None = None
    layout_name = ""
    with ZipFile(BytesIO(zip_data)) as archive:
        names = sorted(archive.namelist())
        artifact_names.extend(names)
        md_name = next(
            (name for name in names if name.rsplit("/", 1)[-1].lower() == "full.md"),
            None,
        )
        if md_name:
            markdown_text = _safe_decode(archive.read(md_name)).strip()
        for name in names:
            base = name.rsplit("/", 1)[-1].lower()
            if base.endswith("content_list.json") or base == "document_content_list.json":
                content_list_raw = archive.read(name)
                content_list_name = name
            if base in {"layout.json", "layout_tree.json"} or base.endswith("_layout.json"):
                layout_raw = archive.read(name)
                layout_name = name
        if not markdown_text and content_list_raw:
            loaded = json.loads(_safe_decode(content_list_raw))
            if isinstance(loaded, list):
                blocks: list[str] = []
                for item in loaded:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        blocks.append(text.strip())
                markdown_text = "\n\n".join(blocks)
    return {
        "artifact_names": artifact_names,
        "markdown_text": markdown_text.strip(),
        "content_list_raw": content_list_raw,
        "content_list_name": content_list_name,
        "layout_raw": layout_raw,
        "layout_name": layout_name,
    }


def _write_outputs(
    *,
    out_dir: Path,
    legacy_md_dir: Path,
    knowledge_file_id: str,
    source: Path,
    extracted: dict[str, Any],
    zip_data: bytes | None,
    keep_zip: bool,
    error: str | None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "full.md"
    meta = {
        "knowledgeFileId": knowledge_file_id,
        "source": str(source),
        "artifact_files": extracted.get("artifact_names") or [],
        "content_list_name": extracted.get("content_list_name") or "",
        "layout_name": extracted.get("layout_name") or "",
        "status": "failed" if error else "success",
        "error": error or "",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    body = (extracted.get("markdown_text") or "").strip() or "(empty)"
    md_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
        + "\n\n# OCR 提取结果\n\n"
        + body
        + "\n",
        encoding="utf-8",
    )
    content_list_raw = extracted.get("content_list_raw")
    if isinstance(content_list_raw, (bytes, bytearray)):
        (out_dir / "content_list.json").write_bytes(content_list_raw)
    layout_raw = extracted.get("layout_raw")
    if isinstance(layout_raw, (bytes, bytearray)):
        (out_dir / "layout.json").write_bytes(layout_raw)
    if keep_zip and zip_data:
        (out_dir / "full.zip").write_bytes(zip_data)
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 兼容旧的按文件名落 md 的习惯
    legacy_md_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = legacy_md_dir / f"{source.name}.md"
    legacy_path.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return md_path


def main() -> None:
    args = _args()
    uploads_root = Path(args.uploads_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    legacy_md_dir = Path(args.legacy_md_dir).resolve()
    checkpoint_path = output_dir / "_checkpoint.json"

    if args.file_id:
        file_ids = args.file_id
        items = _discover_uploads(uploads_root, file_ids)
    elif args.all_uploads:
        items = _discover_all_uploads(uploads_root)
    else:
        file_ids = _active_file_ids(Path(args.baseline_files))
        items = _discover_uploads(uploads_root, file_ids)
    if args.limit > 0:
        items = items[: args.limit]
    if not items:
        print(f"未找到可处理文件: {uploads_root}")
        return
    print(f"queued={len(items)} uploads_root={uploads_root}")

    checkpoint = {"completed": {}, "failed": {}} if args.reset_checkpoint else _load_checkpoint(checkpoint_path)
    client: MinerUClient | None = None
    if not args.dry_run:
        try:
            config = load_mineru_config(validate=False)
            if not config.api_key:
                print("缺少环境变量 AICHECK_MINERU_API_KEY")
                return
            client = MinerUClient(config)
        except MinerUError as exc:
            print(f"MinerU 配置错误: {exc}")
            return

    ok = fail = skipped = 0
    for index, (knowledge_file_id, source) in enumerate(items, start=1):
        out_dir = output_dir / knowledge_file_id
        meta_path = out_dir / "meta.json"
        if (
            not args.overwrite
            and knowledge_file_id in checkpoint.get("completed", {})
            and meta_path.exists()
        ):
            skipped += 1
            print(f"[{index}/{len(items)}] skip checkpoint: {knowledge_file_id}")
            continue
        if args.dry_run:
            print(f"[{index}/{len(items)}] dry-run: {knowledge_file_id} <- {source}")
            continue
        try:
            if client is None:
                raise RuntimeError("MinerU 客户端不可用")
            submission = client.submit_file(
                source,
                data_id=knowledge_file_id,
                options={"language": args.language},
            )
            status = client.wait_for_result(submission)
            if str(status.get("state") or "").lower() != "done":
                raise MinerUJobFailed("MINERU_JOB_UNEXPECTED_STATE", "任务未完成")
            result_url = str(status.get("full_zip_url") or "")
            if not result_url:
                raise MinerUProtocolError("MINERU_RESULT_URL_MISSING", "MinerU 结果 URL 缺失。")
            zip_data = client.download_result(result_url)
            extracted = _extract_sidecar(zip_data)
            if not extracted.get("markdown_text"):
                raise RuntimeError("MinerU 结果无可提取文本")
            _write_outputs(
                out_dir=out_dir,
                legacy_md_dir=legacy_md_dir,
                knowledge_file_id=knowledge_file_id,
                source=source,
                extracted=extracted,
                zip_data=zip_data,
                keep_zip=args.keep_zip,
                error=None,
            )
            checkpoint.setdefault("completed", {})[knowledge_file_id] = {
                "source": str(source),
                "at": datetime.now(timezone.utc).isoformat(),
            }
            checkpoint.get("failed", {}).pop(knowledge_file_id, None)
            ok += 1
            print(f"[{index}/{len(items)}] success: {knowledge_file_id}")
        except Exception as exc:  # noqa: BLE001 — 批量任务需逐文件吞掉并记断点
            fail += 1
            checkpoint.setdefault("failed", {})[knowledge_file_id] = {
                "source": str(source),
                "error": str(exc),
                "at": datetime.now(timezone.utc).isoformat(),
            }
            _write_outputs(
                out_dir=out_dir,
                legacy_md_dir=legacy_md_dir,
                knowledge_file_id=knowledge_file_id,
                source=source,
                extracted={"artifact_names": [], "markdown_text": ""},
                zip_data=None,
                keep_zip=False,
                error=str(exc),
            )
            print(f"[{index}/{len(items)}] fail: {knowledge_file_id} -> {exc}")
        _save_checkpoint(checkpoint_path, checkpoint)

    print(
        f"Done. success={ok} fail={fail} skipped={skipped} "
        f"output_dir={output_dir} checkpoint={checkpoint_path}"
    )


if __name__ == "__main__":
    main()
