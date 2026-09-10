"""对一份真实文件跑一次 agent 事实抽取；只填事实，判定仍由冻结判据算。

这会**真的调用模型、真的花钱**，所以默认只跑一个域、一份文件，并把请求与回复
原样落盘，好让同一笔钱的结果可以反复检查而不用重跑。

    python3 scripts/run_domain_judgment.py \
        --document-version-id DV-x --rules materialCertificateRules \
        --domain materialCertificate --out /tmp/r43-judgment
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from libs.review_orchestrator.domain_judgment_agent import (
    assign_paths,
    build_messages,
    declared_paths,
    page_text,
    parse_response,
)


def domain_spec(pack_id: str, rules_key: str, domain: str) -> dict[str, Any]:
    from libs.business_pack import load_business_pack

    pack = load_business_pack(pack_id)

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("domains"), dict) and domain in node["domains"]:
                yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    for block in walk(pack):
        spec = block["domains"][domain]
        if isinstance(spec, dict):
            return spec
    raise SystemExit(f"找不到域 {domain}（rules={rules_key}），核对规则包里的名字")


def pages_for(parse_results: list[dict[str, Any]], version_id: str, limit: int) -> list[dict[str, Any]]:
    numbers = sorted({
        fragment.get("pageNo")
        for parse in parse_results
        if parse.get("documentVersionId") == version_id
        for fragment in parse.get("fragments") or []
        if isinstance(fragment, dict) and type(fragment.get("pageNo")) is int
    })
    pages = []
    for page_no in numbers[:limit]:
        text = page_text(parse_results, version_id, page_no)
        if text:
            pages.append({"documentVersionId": version_id, "pageNo": page_no, "text": text})
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-version-id", required=True)
    parser.add_argument("--rules", required=True, help="规则包里的 *Rules 键名，仅用于记录")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pack-id", default="engineering_inspection_v1")
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--model", default=os.getenv("AICHECK_JUDGMENT_MODEL", "review-chat"))
    args = parser.parse_args()

    from libs.db import repository
    from libs.review_orchestrator._shared import qwen_runtime_client

    repository.load_state({"ocr_parse_results"})
    parse_results = [
        row for row in repository.repo.state.get("ocr_parse_results") or []
        if row.get("documentVersionId") == args.document_version_id
    ]
    if not parse_results:
        raise SystemExit(f"这个版本没有解析结果：{args.document_version_id}")
    pages = pages_for(parse_results, args.document_version_id, args.max_pages)
    if not pages:
        raise SystemExit("解析结果里没有正文片段，agent 无正文可读")

    spec = domain_spec(args.pack_id, args.rules, args.domain)
    messages = build_messages(args.domain, spec, pages)
    response = qwen_runtime_client().chat_sync(
        messages, model=args.model, temperature=0.0, response_format={"type": "json_object"},
    )
    from libs.qwen_runtime import QwenRuntimeClient

    content = QwenRuntimeClient.first_message_text(response)
    outcome = parse_response(
        content, spec, parse_results,
        allowed_document_version_ids={args.document_version_id},
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "messages.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2))
    (args.out / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2))
    report = {
        "documentVersionId": args.document_version_id,
        "domain": args.domain,
        "declaredPaths": sorted(declared_paths(spec)),
        "filled": outcome["values"],
        "row": assign_paths(outcome["values"]),
        "evidenceRefs": outcome["evidenceRefs"],
        "rejected": outcome["rejected"],
        "usage": response.get("usage"),
        "model": response.get("model"),
        # 这个数字是判断这层值不值得的关键：宣告了多少、真填上多少。
        "coverage": f"{len(outcome['values'])}/{len(declared_paths(spec))}",
    }
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
