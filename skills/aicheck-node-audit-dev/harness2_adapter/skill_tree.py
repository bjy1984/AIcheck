"""Fold the skill's references/ into SKILL.md and back, so the skill fits harness2's editable surface.

harness2 only lets an optimizer edit a fixed set of files (systemprompt.md, guardrails.md, LongTermMEMORY.md,
tool_descriptions/tool_guidance.md, skills/<name>/SKILL.md, skills/<name>/scripts/*, ...). A proposal that carries
any other file, such as our references/*.md, is rejected. So the skill goes in as one SKILL.md with the reference
files folded in behind markers, and what comes back is split at the same markers.

    export  skill dir  ->  harness tree directory
    import  harness tree directory  ->  a NEW skill directory plus a report (never overwrites the live skill)
    check   a harness tree directory against the frozen list
    roundtrip  prove fold/unfold is lossless on a skill directory

Standard library only. Nothing here imports harness2 or calls a model.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

NAME = "aicheck-node-audit"
ROLE = "You audit AIcheck engineering nodes and report each atomic check with page-level evidence.\n"
# Where things live on each harness2 executor's editable surface (harness2 core/tree.py, substrate/*.py).
LAYOUTS = {
    "opencode": {"skill_md": f"skills/{NAME}/SKILL.md", "script": f"skills/{NAME}/scripts/node_audit.py",
                 "always_on": ("systemprompt.md", "guardrails.md", "LongTermMEMORY.md", "tool_descriptions/tool_guidance.md"),
                 "trigger_file": "guardrails.md",
                 "trigger": f"- When auditing an AIcheck engineering node, load the `{NAME}` skill.\n"},
    "codex": {"skill_md": f".agents/skills/{NAME}/SKILL.md", "script": f".agents/skills/{NAME}/scripts/node_audit.py",
              "always_on": ("AGENTS.md",), "trigger_file": "AGENTS.md",
              "trigger": f"- When auditing an AIcheck engineering node, read .agents/skills/{NAME}/SKILL.md and follow it.\n"},
}
SKILL_MD = LAYOUTS["opencode"]["skill_md"]
SCRIPT = LAYOUTS["opencode"]["script"]
ALWAYS_ON = LAYOUTS["opencode"]["always_on"]
# What an optimizer must not be able to delete: masking of ID numbers and the report validator.
FROZEN_SNIPPETS = ("def mask_value", "def is_id_number", "def check_report")

SEPARATOR = "\n\n---\n\n"
MARKER = "<!-- folded from references/{name} -->"
_FOLDED = re.compile(r"\n\n---\n\n<!-- folded from references/([A-Za-z0-9_.-]+\.md) -->\n\n")


class SkillTreeError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def reference_names(skill_dir: Path) -> list[str]:
    return sorted(p.name for p in (Path(skill_dir) / "references").glob("*.md"))


def fold(skill_dir: Path) -> str:
    """SKILL.md followed by every references/*.md, each behind its marker. Lossless: `unfold` undoes it."""
    skill_dir = Path(skill_dir)
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for name in reference_names(skill_dir):
        text += SEPARATOR + MARKER.format(name=name) + "\n\n" + (skill_dir / "references" / name).read_text(encoding="utf-8")
    return text


def unfold(text: str) -> tuple[str, dict[str, str]]:
    """The inverse of `fold`: (SKILL.md text, {reference name: text})."""
    parts = _FOLDED.split(text)
    skill = parts[0]
    refs = {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}
    if len(refs) != (len(parts) - 1) // 2:
        raise SkillTreeError(["the same reference is folded in twice"])
    return skill, refs


def refold(skill: str, refs: dict[str, str]) -> str:
    """Build folded text from its parts (the same layout `fold` writes); references keep the order given."""
    return skill + "".join(SEPARATOR + MARKER.format(name=n) + "\n\n" + t for n, t in refs.items())


def export_tree(skill_dir: Path, layout: str = "opencode") -> dict[str, str]:
    """The harness tree for this skill: relative path -> text, only files on harness2's editable surface."""
    skill_dir, where = Path(skill_dir), LAYOUTS[layout]
    tree = {name: "" for name in where["always_on"]}
    if layout == "opencode":
        tree["systemprompt.md"] = ROLE
        tree["guardrails.md"] = where["trigger"]
    else:
        tree["AGENTS.md"] = ROLE + "\n" + where["trigger"]
    tree[where["skill_md"]] = fold(skill_dir)
    tree[where["script"]] = (skill_dir / "scripts" / "node_audit.py").read_text(encoding="utf-8")
    return tree


def check_tree(tree: dict[str, str], *, expected_references: list[str] | None = None, layout: str = "opencode") -> list[str]:
    """Problems that make a tree unfit to become the skill again. Empty means fine."""
    where = LAYOUTS[layout]
    problems = []
    script = tree.get(where["script"], "")
    for snippet in FROZEN_SNIPPETS:
        if snippet not in script:
            problems.append(f"{where['script']} must keep `{snippet}` (masking and report validation are frozen)")
    if where["skill_md"] not in tree:
        problems.append(f"{where['skill_md']} is missing")
        return problems
    try:
        _skill, refs = unfold(tree[where["skill_md"]])
    except SkillTreeError as exc:
        return problems + exc.problems
    for name in expected_references or []:
        if name not in refs:
            problems.append(f"the folded reference {name} is gone; its marker `{MARKER.format(name=name)}` must stay")
    return problems


def read_tree_dir(root: Path) -> dict[str, str]:
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


def write_tree_dir(tree: dict[str, str], dest: Path) -> None:
    for rel, text in tree.items():
        target = Path(dest) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def import_tree(tree: dict[str, str], out_dir: Path, *, base_skill_dir: Path | None = None, layout: str = "opencode") -> dict[str, Any]:
    """Write an adopted harness tree out as a skill directory (SKILL.md, references/, scripts/).

    `out_dir` must not exist: the live skill is never overwritten, a person reviews the diff and copies over.
    With `base_skill_dir` the report says which files changed and which harness-only files (the always-on ones,
    which have no counterpart in the skill) differ from a fresh export.
    """
    where = LAYOUTS[layout]
    base = export_tree(base_skill_dir, layout) if base_skill_dir else None
    expected = reference_names(base_skill_dir) if base_skill_dir else None
    problems = check_tree(tree, expected_references=expected, layout=layout)
    if problems:
        raise SkillTreeError(problems)
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise SkillTreeError([f"{out_dir} already exists; import writes a new directory"])
    skill_text, refs = unfold(tree[where["skill_md"]])
    files = {"SKILL.md": skill_text, "scripts/node_audit.py": tree[where["script"]], **{f"references/{n}": t for n, t in refs.items()}}
    write_tree_dir(files, out_dir)
    report: dict[str, Any] = {"written": sorted(files), "outDir": str(out_dir)}
    if base_skill_dir:
        was = {"SKILL.md": (Path(base_skill_dir) / "SKILL.md").read_text(encoding="utf-8"),
               "scripts/node_audit.py": base[where["script"]],
               **{f"references/{n}": (Path(base_skill_dir) / "references" / n).read_text(encoding="utf-8") for n in expected}}
        report["changed"] = sorted(rel for rel, text in files.items() if was.get(rel) != text)
        report["addedFiles"] = sorted(set(files) - set(was))
        report["harnessOnlyChanged"] = sorted(rel for rel in tree if rel not in {where["skill_md"], where["script"]} and base.get(rel) != tree[rel])
    return report


def _print(ok: bool, payload: Any) -> int:
    print(json.dumps({"ok": ok, ("data" if ok else "error"): payload}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="skill directory -> harness tree directory")
    p.add_argument("--skill-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--layout", choices=sorted(LAYOUTS), default="opencode")
    p = sub.add_parser("import", help="harness tree directory -> a new skill directory plus a change report")
    p.add_argument("--harness", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--skill-dir", type=Path, help="the live skill to compare against")
    p.add_argument("--layout", choices=sorted(LAYOUTS), default="opencode")
    p = sub.add_parser("check", help="check a harness tree directory against the frozen list")
    p.add_argument("--harness", type=Path, required=True)
    p.add_argument("--skill-dir", type=Path)
    p.add_argument("--layout", choices=sorted(LAYOUTS), default="opencode")
    p = sub.add_parser("roundtrip", help="prove fold/unfold loses nothing on a skill directory")
    p.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            if args.out.exists():
                raise SkillTreeError([f"{args.out} already exists"])
            write_tree_dir(export_tree(args.skill_dir, args.layout), args.out)
            return _print(True, {"harness": str(args.out)})
        if args.command == "import":
            return _print(True, import_tree(read_tree_dir(args.harness), args.out, base_skill_dir=args.skill_dir, layout=args.layout))
        if args.command == "check":
            problems = check_tree(read_tree_dir(args.harness), expected_references=reference_names(args.skill_dir) if args.skill_dir else None, layout=args.layout)
            return _print(not problems, {"problems": problems} if problems else {"problems": []})
        skill, refs = unfold(fold(args.skill_dir))
        same = skill == (args.skill_dir / "SKILL.md").read_text(encoding="utf-8") and all(
            refs.get(n) == (args.skill_dir / "references" / n).read_text(encoding="utf-8") for n in reference_names(args.skill_dir))
        return _print(same and set(refs) == set(reference_names(args.skill_dir)), {"lossless": same, "references": sorted(refs)})
    except SkillTreeError as exc:
        return _print(False, {"problems": exc.problems})


if __name__ == "__main__":
    sys.exit(main())
