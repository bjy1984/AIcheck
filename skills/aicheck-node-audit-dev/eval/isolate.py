"""Isolate one trial run of the node-audit skill from the gold answers, then archive it and put everything back.

  prepare  hide the audit home (it holds the gold answers and old results), give the runner a clean copy of one
           project and its own audit home, remember which files already exist in the repo
  prompt   print the trial prompt for one node
  stash    after each node: move its bundle out of the runner's reach, report (or move) files it left behind
  finish   stash what is left, check everything for full ID numbers, delete the runner's copy, restore the home
  scan     look through a runner's transcript for peeks at answers, direct PDF reading and full ID numbers
  status   show what is hidden right now

Standard library only. Nothing here calls a model or touches the server.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "aicheck-node-audit" / "scripts" / "node_audit.py"
REPO = Path(__file__).resolve().parents[3]
PROMPT_TEMPLATE = Path(__file__).resolve().parent / "codex-prompt.txt"
AUDIT_DIR, HOLD_DIR = ".aicheck-node-audit", ".aicheck-node-audit.hold"
TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".gif", ".webp"}
# Strings a runner has no business touching; the trial prompt must not contain them itself.
LEAK_PATTERNS = {
    "标准答案目录": r"eval/gold|gold-work|/gold/",
    "被藏起来的目录": r"\.aicheck-node-audit\.hold",
    "旧评测结果": r"eval/runs",
    "记忆文件": r"/memory/|MEMORY\.md",
    "评估文档": r"claude\.ai/artifact|4YUBToti",
}
# Lines the harness itself writes into a Claude Code transcript (system prompt snapshot, the memory index that is loaded
# into every agent, copies of earlier requests). They are not something the runner did, so they are not peeks.
HARNESS_LINE_TYPES = {"api-request-blob", "api-request-shape"}
HARNESS_ATTACHMENT_TYPES = {"instructions", "prompt_snapshot"}
OTHER_RUN_HOME = re.compile(r"\.aicheck-node-audit-([A-Za-z0-9_-]+)")
DIRECT_PDF_READ = re.compile(r"fitz\.open|pymupdf\.open|PdfReader|pdfplumber|pdftotext", re.IGNORECASE)


class IsolateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def load_node_audit() -> Any:
    spec = importlib.util.spec_from_file_location("node_audit_for_isolate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def locations(args: argparse.Namespace) -> dict[str, Path]:
    tag = getattr(args, "tag", None)
    if tag is not None and not TAG.match(tag):
        raise IsolateError("invalidTag", "--tag 只能用字母、数字、下划线和连字符，最长 41 个字符。")
    home = Path(args.home).expanduser() if args.home else Path.home()
    found = {"home": home, "audit": home / AUDIT_DIR, "hold": home / HOLD_DIR}
    if tag:
        found["runHome"] = home / f"{AUDIT_DIR}-{tag}"
    return found


def tighten(root: Path) -> None:
    """Directories 0700, files 0600: the copy holds real project documents."""
    os.chmod(root, 0o700)
    for current, dirs, files in os.walk(root):
        for name in dirs:
            os.chmod(Path(current) / name, 0o700)
        for name in files:
            os.chmod(Path(current) / name, 0o600)


def full_id_hits(node_audit: Any, text: str) -> list[str]:
    """Masked form of every valid ID number; a JSON-escaped newline before the number must not hide it."""
    flat = text.replace("\\n", "\n").replace("\\t", "\t")
    return [node_audit.mask_ids(m.group(1)) for m in node_audit.ID_CANDIDATE.finditer(flat) if node_audit.is_id_number(m.group(1))]


def git_state(repo: Path) -> dict[str, str]:
    """Path → two-letter status for everything git sees as changed or untracked (empty when not a repo)."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "-z", "--untracked-files=all"],
                             capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError):
        return {}
    state, parts = {}, iter(out.split("\0"))
    for entry in parts:
        if len(entry) < 4:
            continue
        state[entry[3:]] = entry[:2]
        if entry[0] in "RC":
            next(parts, None)  # rename 的原路径
    return state


def walk_files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} if root.is_dir() else set()


def archive_of(where: dict[str, Path], tag: str) -> Path:
    return where["hold"] / "eval" / "runs" / tag


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    where = locations(args)
    project = Path(args.project).expanduser().resolve()
    repo = Path(args.repo).expanduser().resolve() if args.repo else REPO
    watch = [Path(w).expanduser().resolve() for w in args.watch or []]
    if not project.is_dir():
        raise IsolateError("projectMissing", f"{project} 不是目录。")
    if where["hold"].exists():
        raise IsolateError("holdExists", f"{where['hold']} 已存在：上一次试跑没有还原。先跑 finish，或手工确认后改回 {AUDIT_DIR}。")
    if where["runHome"].exists():
        raise IsolateError("runHomeExists", f"{where['runHome']} 已存在，换一个 --tag。")
    if not where["audit"].is_dir():
        raise IsolateError("auditHomeMissing", f"{where['audit']} 不存在，没有可隐藏的目录。")
    if archive_of({"hold": where["audit"]}, args.tag).exists():
        raise IsolateError("tagExists", f"已有归档 {args.tag}，换一个 --tag。")
    copy = where["runHome"] / "projects" / project.name
    try:  # 先复制再改名：项目目录可能就在审计目录里
        shutil.copytree(project, copy)
        (where["runHome"] / "runs").mkdir()
        tighten(where["runHome"])
    except OSError:
        shutil.rmtree(where["runHome"], ignore_errors=True)
        raise
    baseline = {"repo": str(repo), "git": git_state(repo), "watch": {str(w): sorted(walk_files(w)) for w in watch}}
    where["audit"].rename(where["hold"])
    archive = archive_of(where, args.tag)
    (archive / "runs").mkdir(parents=True)
    (archive / "transcripts").mkdir()
    (archive / "baseline.json").write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    return {"runHome": str(where["runHome"]), "projectDir": str(copy), "runsDir": str(where["runHome"] / "runs"),
            "transcriptsDir": str(archive / "transcripts"), "hiddenAs": str(where["hold"]),
            "env": {"AICHECK_AUDIT_HOME": str(where["runHome"])},
            "next": ["用 prompt 子命令生成每个节点的提示词；每个节点开一个全新会话",
                     "每个节点跑完立刻 scan 过程记录、stash 结果，再开下一个节点",
                     "全部跑完执行 finish，目录才会还原"]}


def prompt(args: argparse.Namespace) -> dict[str, Any]:
    where = locations(args)
    node = f"{int(args.node):02d}"
    project_dir = Path(args.project_dir).expanduser()
    out_dir = where["runHome"] / "runs" / f"{args.agent}-{args.label or project_dir.name}-node-{node}"
    text = PROMPT_TEMPLATE.read_text(encoding="utf-8").format(
        repo=args.repo or REPO, project_dir=project_dir, node=node, project_label=args.label or f"TEST-{project_dir.name}",
        out_dir=out_dir, run_home=where["runHome"], base_url=args.base_url, python=args.python)
    return {"outDir": str(out_dir), "prompt": text}


def stash_run(where: dict[str, Path], tag: str, move_stray: bool, move_repo: list[str] | None = None) -> dict[str, Any]:
    """Move the runner's bundles into the archive and see what else it left in the repo or watched folders."""
    archive = archive_of(where, tag)
    if not (archive / "baseline.json").is_file():
        raise IsolateError("notPrepared", f"{archive} 没有基线：没有 prepare 过这个 --tag。")
    baseline = json.loads((archive / "baseline.json").read_text(encoding="utf-8"))
    stashed = []
    for child in sorted((where["runHome"] / "runs").iterdir()):
        if (archive / "runs" / child.name).exists():
            raise IsolateError("archiveExists", f"归档里已有 {child.name}，先手工处理。")
        shutil.move(str(child), archive / "runs" / child.name)
        stashed.append(child.name)
    repo = Path(baseline["repo"])
    new_repo = {p: code for p, code in git_state(repo).items() if p not in baseline["git"]}
    new_watch = {w: sorted(walk_files(Path(w)) - set(old)) for w, old in baseline["watch"].items()}
    moved = []
    if move_stray:
        # 仓库里新冒出的文件只报告（newInRepo），不移动：同一个仓库里常有别的会话在写，分不出是谁建的。
        # c 轮评测这里把别的会话刚建的 138 个文件（测试、页面截图）移进了归档，约 4 分钟后才移回。
        # 只移 --watch 目录（每个跑评测的 agent 自己的工作目录）里新出现的；仓库里确认是执行者留下的（比如带着结论的
        # 脚本，下一个节点会读到），看过 newInRepo 后用 --move-repo 点名移走。
        for w, rels in new_watch.items():
            for rel in rels:
                target = archive / "stray" / "watch" / Path(w).name / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(Path(w) / rel), target)
                moved.append(f"{w}:{rel}")
    for rel in move_repo or []:
        if new_repo.get(rel) != "??":
            raise IsolateError("notStray", f"{rel} 不是这次新冒出的未跟踪文件（看 newInRepo），不移动。")
        target = archive / "stray" / "repo" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(repo / rel), target)
        moved.append(f"repo:{rel}")
    return {"stashed": stashed, "newInRepo": new_repo, "newInWatched": {w: r for w, r in new_watch.items() if r},
            "movedStray": moved}


def stash(args: argparse.Namespace) -> dict[str, Any]:
    where = locations(args)
    if not where["hold"].is_dir():
        raise IsolateError("notPrepared", f"{where['hold']} 不存在：没有 prepare 过，或已经还原。")
    result = stash_run(where, args.tag, args.move_stray, args.move_repo)
    node_audit = load_node_audit()
    result["fullIdNumbersFound"] = scan_tree(node_audit, archive_of(where, args.tag) / "runs", only=result["stashed"])
    return result


def finish(args: argparse.Namespace) -> dict[str, Any]:
    where = locations(args)
    if not where["hold"].is_dir():
        raise IsolateError("notPrepared", f"{where['hold']} 不存在：没有 prepare 过，或已经还原。")
    if where["audit"].exists():
        raise IsolateError("auditHomeExists", f"{where['audit']} 已存在，不能还原；先手工处理。")
    if not where["runHome"].is_dir():
        raise IsolateError("runHomeMissing", f"{where['runHome']} 不存在。")
    result = stash_run(where, args.tag, args.move_stray, args.move_repo)
    archive = archive_of(where, args.tag)
    stray = [c for c in where["runHome"].iterdir() if c.name not in {"projects", "runs"}]
    if stray:
        (archive / "stray" / "run-home").mkdir(parents=True, exist_ok=True)
        for child in stray:
            shutil.move(str(child), archive / "stray" / "run-home" / child.name)
    result["strayFiles"] = [c.name for c in stray]
    result["fullIdNumbersFound"] = scan_tree(load_node_audit(), archive)
    if where["runHome"].name != f"{AUDIT_DIR}-{args.tag}":  # 只删自己建的副本
        raise IsolateError("unsafeDelete", "拒绝删除名字不对的目录。")
    shutil.rmtree(where["runHome"])
    for current, _dirs, files in os.walk(archive):
        os.chmod(current, 0o700)
        for name in files:
            os.chmod(Path(current) / name, 0o600)
    where["hold"].rename(where["audit"])
    result.update({"archive": str(archive), "restored": str(where["audit"])})
    return result


def scan_tree(node_audit: Any, root: Path, only: list[str] | None = None) -> dict[str, int]:
    """Full ID numbers in everything the runner wrote except the original documents and images."""
    hits: dict[str, int] = {}
    for current, _dirs, files in os.walk(root):
        rel = Path(current).relative_to(root)
        if "files" in rel.parts or (only is not None and rel.parts and rel.parts[0] not in only):
            continue
        if only is not None and not rel.parts:  # 顶层散落的文件也只查点名的
            files = [f for f in files if f in only]
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() in BINARY_SUFFIXES:
                continue
            count = len(full_id_hits(node_audit, path.read_text(encoding="utf-8", errors="ignore")))
            if count:
                hits[str(path.relative_to(root))] = count
    return hits


def is_harness_line(line: str) -> bool:
    """A JSONL line the harness wrote (not the runner): skipped by scan, and counted."""
    if not line.startswith("{"):
        return False
    try:
        record = json.loads(line)
    except ValueError:
        return False
    if not isinstance(record, dict):
        return False
    attachment = record.get("attachment")
    return record.get("type") in HARNESS_LINE_TYPES or (isinstance(attachment, dict) and attachment.get("type") in HARNESS_ATTACHMENT_TYPES)


def scan(args: argparse.Namespace) -> dict[str, Any]:
    node_audit = load_node_audit()
    leak = {name: re.compile(pattern) for name, pattern in LEAK_PATTERNS.items()}
    reports = []
    for name in args.files:
        path = Path(name).expanduser()
        if not path.is_file():
            raise IsolateError("fileNotFound", f"{path} 不存在。")
        found: dict[str, list[dict[str, Any]]] = {}
        ids, pdf_reads, skipped = [], [], 0
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if is_harness_line(line):
                skipped += 1
                continue
            masked_line = node_audit.mask_ids(line.replace("\\n", "\n"))
            for label, pattern in leak.items():
                if pattern.search(line):
                    found.setdefault(label, []).append({"line": number, "text": masked_line.strip()[:160]})
            for other in OTHER_RUN_HOME.findall(line):
                if other != args.tag:
                    found.setdefault("别的试跑目录", []).append({"line": number, "text": masked_line.strip()[:160]})
            if full_id_hits(node_audit, line):
                ids.append({"line": number, "text": masked_line.strip()[:160]})
            if DIRECT_PDF_READ.search(line):
                pdf_reads.append({"line": number, "text": masked_line.strip()[:160]})
        reports.append({"file": str(path), "peeks": {k: {"count": len(v), "first": v[:3]} for k, v in found.items()},
                        "fullIdNumberLines": {"count": len(ids), "first": ids[:3]},
                        "directPdfReads": {"count": len(pdf_reads), "first": pdf_reads[:3]},
                        "harnessLinesSkipped": skipped})
    return {"files": reports,
            "note": "命中只说明这些字符串出现过，要看上下文：提示词和工具输出里出现、不等于执行者去读了。完整号码要看是哪条命令带出来的。"}


def status(args: argparse.Namespace) -> dict[str, Any]:
    where = locations(args)
    homes = sorted(p.name for p in where["home"].glob(f"{AUDIT_DIR}-*"))
    return {"auditHomePresent": where["audit"].exists(), "hiddenPresent": where["hold"].exists(), "runHomes": homes,
            "hint": "hiddenPresent 为 true 说明有试跑没还原，先跑 finish。" if where["hold"].exists() else ""}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root.add_argument("--home", help="主目录（默认当前用户的；测试用）")
    sub = root.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="隐藏审计目录，复制项目，建试跑目录，记下仓库里已有的文件")
    p.add_argument("--tag", required=True, help="这次试跑的名字，如 r11-codex")
    p.add_argument("--project", required=True, help="要复制给试跑者的项目目录")
    p.add_argument("--repo", help="试跑者工作的仓库（默认本仓库）；用 git 记下已有文件")
    p.add_argument("--watch", action="append", help="再盯一个试跑者可写的目录（如临时目录），可重复")
    p.set_defaults(func=prepare)
    p = sub.add_parser("prompt", help="打印一个节点的试跑提示词")
    p.add_argument("--tag", required=True)
    p.add_argument("--node", required=True, help="节点号，如 24")
    p.add_argument("--project-dir", required=True, help="prepare 返回的 projectDir")
    p.add_argument("--base-url", required=True, help="服务器地址，如 http://主机:端口")
    p.add_argument("--agent", default="codex", help="资料包目录名前缀")
    p.add_argument("--label", help="项目标签（默认 TEST-项目目录名）")
    p.add_argument("--python", default="backend/.venv/bin/python", help="装了 PyMuPDF 的 Python")
    p.add_argument("--repo", help="提示词里写的仓库路径（默认本仓库）")
    p.add_argument("--raw", action="store_true", help="只打印提示词本身，方便管道给执行者")
    p.set_defaults(func=prompt)
    p = sub.add_parser("stash", help="每个节点跑完后：结果移出试跑者够得着的地方，列出它在仓库里留下的新文件")
    p.add_argument("--tag", required=True)
    p.add_argument("--move-stray", action="store_true", help="把 --watch 目录里新冒出的文件也移进归档（仓库里新冒出的只报告，不移动）")
    p.add_argument("--move-repo", nargs="+", metavar="REL", help="把仓库里点名的这几个新冒出的未跟踪文件移进归档（先看 newInRepo，确认是执行者留下的）")
    p.set_defaults(func=stash)
    p = sub.add_parser("finish", help="归档剩余结果、查完整身份证号、还原目录")
    p.add_argument("--tag", required=True)
    p.add_argument("--move-stray", action="store_true", help="把 --watch 目录里新冒出的文件也移进归档（仓库里新冒出的只报告，不移动）")
    p.add_argument("--move-repo", nargs="+", metavar="REL", help="把仓库里点名的这几个新冒出的未跟踪文件移进归档（先看 newInRepo，确认是执行者留下的）")
    p.set_defaults(func=finish)
    p = sub.add_parser("scan", help="扫试跑者的过程记录")
    p.add_argument("files", nargs="+", help="过程记录文件（任何文本格式）")
    p.add_argument("--tag", help="本次试跑的名字，它自己的目录不算“别的试跑目录”")
    p.set_defaults(func=scan)
    p = sub.add_parser("status", help="看有没有没还原的试跑")
    p.set_defaults(func=status)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        data = args.func(args)
        print(data["prompt"] if args.command == "prompt" and args.raw else json.dumps({"ok": True, "data": data}, ensure_ascii=False, indent=2))
        return 0
    except IsolateError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
