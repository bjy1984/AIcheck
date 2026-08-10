#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from io import BytesIO
from pathlib import Path
import sys
from typing import Any
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
INPUT_DEFAULT = ROOT / "rules" / "standards"
OUTPUT_DEFAULT = ROOT / "rules" / "results"

if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from libs.integrations.mineru_client import (
    MinerUProtocolError,
    MinerUError,
    MinerUJobFailed,
    MinerUClient,
    load_mineru_config,
)

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".doc",
    ".png",
    ".jpg",
    ".jpeg",
    ".heic",
    ".heif",
    ".tiff",
    ".txt",
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use MinerU OCR to process rules/standards and write md outputs to rules/results.",
    )
    parser.add_argument(
        "--input-dir",
        default=str(INPUT_DEFAULT),
        help="Input directory, default: rules/standards.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DEFAULT),
        help="Output directory, default: rules/results.",
    )
    parser.add_argument(
        "--language",
        default="ch",
        help="MinerU language option.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing md outputs.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not recurse into subdirectories.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only first N files.",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="Start from 1-based index in sorted input list.",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        default=0,
        help="Process up to this 1-based index (0 means end).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files and simulate without calling MinerU.",
    )
    return parser.parse_args()


def _find_files(input_dir: Path, recursive: bool) -> list[Path]:
    if not input_dir.is_dir():
        raise RuntimeError(f"输入目录不存在: {input_dir}")
    iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
    return sorted(
        path
        for path in iterator
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _safe_decode(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _to_markdown_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _front_matter(payload: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in payload.items():
        if isinstance(value, (list, dict)):
            lines.append(f'{key}: {json.dumps(value, ensure_ascii=False)}')
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f'{key}: "{_to_markdown_escape(str(value))}"')
    lines.append("---")
    return "\n".join(lines)


def _strip_yaml_front(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2] if len(parts) >= 3 else text


def _extract_content_from_mineru_zip(data: bytes) -> tuple[list[str], str]:
    artifact_names: list[str] = []
    markdown_text = ""
    content_list_text = ""
    content_count = 0
    with ZipFile(BytesIO(data)) as archive:
        names = sorted(archive.namelist())
        artifact_names.extend(names)
        md_name = next(
            (
                name
                for name in names
                if name.rsplit("/", 1)[-1].lower() == "full.md"
            ),
            None,
        )
        if md_name:
            markdown_text = _safe_decode(archive.read(md_name)).strip()
        if not markdown_text:
            content_name = next(
                (
                    name
                    for name in names
                    if name.endswith("_content_list.json")
                    or name.endswith("/document_content_list.json")
                ),
                None,
            )
            if content_name:
                loaded = _safe_decode(archive.read(content_name))
                raw = json.loads(loaded)
                if isinstance(raw, list):
                    blocks: list[str] = []
                    for index, item in enumerate(raw):
                        if not isinstance(item, dict):
                            continue
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            blocks.append(text.strip())
                            content_count += 1
                            continue
                        if str(item.get("type") or "").lower() == "table":
                            html = item.get("table_body") or item.get("html")
                            if isinstance(html, str) and html.strip():
                                blocks.append(
                                    " ".join(
                                        segment.strip()
                                        for segment in html.replace("<", " <").replace(
                                            ">",
                                            "> ",
                                        ).split()
                                        if segment.strip()
                                    )
                                )
                                content_count += 1
                    content_list_text = "\n\n".join(blocks)
                del raw
    text = markdown_text or content_list_text
    if content_count:
        text = f"{text}\n\n<!-- fragments: {content_count} -->"
    return artifact_names, text.strip()


def _output_path(output_root: Path, source: Path, input_dir: Path) -> Path:
    rel = source.relative_to(input_dir)
    target_dir = output_root / rel.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{source.name}.md"


def _write_md(path: Path, *, source: Path, relative: Path, text: str, artifacts: list[str], error: str | None) -> None:
    front = _front_matter(
        {
            "source": str(source),
            "relative_path": str(relative),
            "artifacts_count": len(artifacts),
            "artifact_files": artifacts,
            "status": "failed" if error else "success",
            "error": error or "",
        }
    )
    content = text.strip() or "(empty)"
    if front:
        out = f"{front}\n\n# OCR 提取结果\n\n{content}\n"
    else:
        out = f"# OCR 提取结果\n\n{content}\n"
    path.write_text(out, encoding="utf-8")


def main() -> None:
    args = _args()
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    files = _find_files(input_dir, recursive=not args.no_recursive)
    if args.start_index <= 0:
        args.start_index = 1
    if args.end_index and args.end_index < args.start_index:
        raise RuntimeError("end-index 必须大于等于 start-index，或为 0")
    files = files[args.start_index - 1 :]
    if args.end_index:
        files = files[: args.end_index - args.start_index + 1]
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        print(f"未找到可处理文件: {input_dir}")
        return

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
    
    ok, fail = 0, 0
    for i, source in enumerate(files, start=1):
        relative = source.relative_to(input_dir)
        out = _output_path(output_dir, source, input_dir)
        if not args.overwrite and out.exists():
            print(f"[{i}/{len(files)}] skip exists: {out}")
            continue
        if args.dry_run:
            print(f"[{i}/{len(files)}] dry-run: {source} -> {out}")
            continue
        try:
            if client is None:
                raise RuntimeError("MinerU 客户端不可用")
            submission = client.submit_file(
                source,
                data_id=source.name,
                options={"language": args.language},
            )
            status = client.wait_for_result(submission)
            if str(status.get("state") or "").lower() != "done":
                raise MinerUJobFailed("MINERU_JOB_UNEXPECTED_STATE", "任务未完成")
            result_url = str(status.get("full_zip_url") or "")
            if not result_url:
                raise MinerUProtocolError(
                    "MINERU_RESULT_URL_MISSING",
                    "MinerU 结果 URL 缺失。",
                )
            zip_data = client.download_result(result_url)
            artifacts, text = _extract_content_from_mineru_zip(zip_data)
            if not text:
                raise RuntimeError("MinerU 结果无可提取文本")
            _write_md(
                out,
                source=source,
                relative=relative,
                text=text,
                artifacts=artifacts,
                error=None,
            )
            ok += 1
            print(f"[{i}/{len(files)}] success: {source.name} -> {out}")
        except Exception as exc:
            fail += 1
            _write_md(
                out,
                source=source,
                relative=relative,
                text="",
                artifacts=[],
                error=str(exc),
            )
            print(f"[{i}/{len(files)}] fail: {source.name} -> {exc}")

    print(f"Done. success={ok} fail={fail} output_dir={output_dir}")


if __name__ == "__main__":
    main()
