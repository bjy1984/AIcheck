"""打节点审计 skill 的安装包（2026-11-04）。

部署时在服务器上用**这次要部署的那棵树**跑一次，产物放进 backend/skill_package/，随 API 镜像一起上线；
平台「安装节点审计 skill」给出的一次性链接就下载这一份。本机开发、测试时 API 找不到产物会现打一份。

包里有什么（和 2026-10-29 手工打的包一样的结构，包根目录叫 aicheck-node-audit-skill/）：
- README.md：skills/aicheck-node-audit-dev/package/README.md
- skills/aicheck-node-audit/：skill 本体（不带缓存目录）
- backend/business_packs/engineering_inspection_v1/：审计规则
- rules/standards/：standards.txt 列的那几份标准原文（skill 页码表引用的）

SKILL.md 在「准备」前面加一行包根目录占位符，安装说明让 AI 助手解压后换成真实路径：
以后在别的目录起会话，它也知道先 cd 到哪里再跑命令。

压缩包里每个条目的时间戳固定，同一棵树打出来的包逐字节相同，校验值不随打包时间变。

用法：python scripts/build_skill_package.py --repo .. --out skill_package [--revision <提交号>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

PACKAGE_ROOT = "aicheck-node-audit-skill"
ZIP_NAME = "aicheck-node-audit-skill.zip"
INFO_NAME = "package.json"
SPEC_DIR = Path("skills/aicheck-node-audit-dev/package")
SKILL_DIR = Path("skills/aicheck-node-audit")
PACK_DIR = Path("backend/business_packs/engineering_inspection_v1")
STANDARDS_DIR = Path("rules/standards")
ROOT_PLACEHOLDER = "__AICHECK_PACKAGE_ROOT__"
ROOT_LINE = (
    f"包根目录：`{ROOT_PLACEHOLDER}`。下面的命令都按包根目录写：会话不在这个目录时，先 `cd` 过去再跑。\n\n"
)
SKIPPED_PARTS = {"__pycache__", ".ruff_cache", ".pytest_cache", ".DS_Store"}
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def package_files(repo: Path) -> list[tuple[str, Path]]:
    """(包内路径, 仓库里的源文件)，按包内路径排好。缺文件直接报错：少一份标准，skill 会静默读不到。"""
    files: list[tuple[str, Path]] = [("README.md", repo / SPEC_DIR / "README.md")]
    for directory in (SKILL_DIR, PACK_DIR):
        for path in sorted((repo / directory).rglob("*")):
            if path.is_file() and not SKIPPED_PARTS.intersection(path.relative_to(repo).parts):
                files.append((path.relative_to(repo).as_posix(), path))
    names = [line.strip() for line in (repo / SPEC_DIR / "standards.txt").read_text(encoding="utf-8").splitlines()]
    for name in filter(None, names):
        files.append(((STANDARDS_DIR / name).as_posix(), repo / STANDARDS_DIR / name))
    missing = [str(source) for _, source in files if not source.is_file()]
    if missing:
        raise SystemExit(f"打包缺文件：{missing}")
    return sorted(files)


def skill_md_with_root_line(text: str) -> str:
    """在「## 准备」前面插一行包根目录占位符（只插一次）。"""
    if ROOT_PLACEHOLDER in text:
        return text
    marker = "## 准备"
    index = text.find(marker)
    return text[:index] + ROOT_LINE + text[index:] if index >= 0 else ROOT_LINE + text


def build(repo: Path, out: Path, revision: str = "") -> dict:
    repo, out = repo.resolve(), out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / ZIP_NAME
    partial = out / f"{ZIP_NAME}.partial"
    entries = package_files(repo)
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for inner, source in entries:
            data = source.read_bytes()
            if inner == (SKILL_DIR / "SKILL.md").as_posix():
                data = skill_md_with_root_line(data.decode("utf-8")).encode("utf-8")
            info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/{inner}", date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if inner.endswith(".py") else 0o644) << 16
            archive.writestr(info, data)
    partial.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    info = {"name": PACKAGE_ROOT, "fileName": ZIP_NAME, "revision": revision, "sha256": digest,
            "size": target.stat().st_size, "fileCount": len(entries),
            "builtAt": datetime.now(UTC).isoformat(timespec="seconds")}
    (out / INFO_NAME).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "skill_package"))
    parser.add_argument("--revision", default="")
    args = parser.parse_args(argv)
    info = build(Path(args.repo), Path(args.out), args.revision)
    print(f"skill 安装包：{info['fileCount']} 个文件，{info['size'] / 1048576:.1f} MB，sha256 {info['sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
