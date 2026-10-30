#!/usr/bin/env python3
"""把从服务器拉的资料包改成盲评包：去掉服务器的审查结论，资料、挂载、OCR、规则不动。

量“skill 和服务器谁更准”时用（2026-10-29 服务器 8 节点评测）：digest.md 每项写着服务器结果，
workspace.json 的 aiReview 有服务器 AI 审查的全过程，skill 照流程读 digest 就会被带偏。

    python3 blind_bundle.py <资料包> [<资料包> …]

去掉的：bundle.json 的 serverOutcomes 和 parts.reviewRun、review-run.json（包根和 ocr/server/ 两份）、
workspace.json 的 aiReview（两份）；然后按改过的清单重写 digest.md（服务器结果一栏变成“—”）。
evidence-chain.json 留着：那是证据挂在哪页，属于输入；sync、cert-registry 回查证号要用。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "aicheck-node-audit" / "scripts"))
import node_audit as na  # noqa: E402


def blind(bundle: Path) -> dict:
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    if manifest.get("source") != "server":
        raise SystemExit(f"{bundle}：不是从服务器拉的资料包（source={manifest.get('source')}）")
    removed = []
    if manifest.get("serverOutcomes"):
        removed.append("bundle.json serverOutcomes")
    manifest["serverOutcomes"] = {}
    if (manifest.get("parts") or {}).pop("reviewRun", None):
        removed.append("bundle.json parts.reviewRun")
    for relative in ("review-run.json", f"{na.SERVER_RAW_DIR}/review-run.json"):
        if (bundle / relative).exists():
            (bundle / relative).unlink()
            removed.append(relative)
    for relative in ("workspace.json", f"{na.SERVER_RAW_DIR}/workspace.json"):
        path = bundle / relative
        if not path.exists():
            continue
        workspace = json.loads(path.read_text(encoding="utf-8"))
        if workspace.get("aiReview"):
            workspace["aiReview"] = {}
            na.write_private(path, na.dump(workspace))  # 包根那份读进来时已脱敏，原样写回
            removed.append(f"{relative} aiReview")
    manifest["blindedAt"] = na.now()
    na.write_private(bundle / "bundle.json", na.dump(manifest))
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
    workspace = json.loads((bundle / "workspace.json").read_text(encoding="utf-8"))
    na.write_digest(bundle, manifest, rules, workspace)
    return {"bundle": str(bundle), "removed": removed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundles", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([blind(b.expanduser().resolve()) for b in args.bundles], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
