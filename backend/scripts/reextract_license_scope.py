"""把已解析资料里的错误「许可范围」重抽一遍。

## 为什么需要这个脚本

修好抽取器只影响**以后**解析的资料。已经解析过的那些，库里存的还是错值
——而且错值会顺着 rule_check_results / review_runs 一路扩散到审查结论。

2026-08-17 线上实测：4 份资料的 license_scope 是「以下特种设备生产活动」，
rule_check_results 里有 226 处引用。**修代码不等于修数据。**

好消息是 ocr_parse_results 里已经存了 fragments 和 tables，
不需要重新 OCR、不需要再花一次钱，只要重跑字段抽取。

## 用法

    docker exec aicheck-api python3 /app/scripts/reextract_license_scope.py --dry-run
    docker exec aicheck-api python3 /app/scripts/reextract_license_scope.py --apply

默认 dry-run。**先看清要改什么再改**——这是直接改线上数据。

## 注意

只重抽 license_scope 这一个字段，且只在现值**通不过可用性校验**时才动。
现值正确的一律不碰：批量重写正确数据的风险远大于收益。

重抽之后审查结论不会自动更新——那些要靠监检人员重跑节点（ai-recheck）。
脚本会把受影响的文档列出来，方便决定要不要重跑。
"""

from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, "/app")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真的写回；不带则只看不改")
    args = parser.parse_args()

    from apps.ocr_service.service import (
        license_scope_text_is_usable,
        qualification_scope_candidate,
    )
    from libs.db.repository import flush_state, load_state, repo

    load_state()
    results = repo.state.get("ocr_parse_results") or []
    if not isinstance(results, list):
        print("ocr_parse_results 不是列表，放弃")
        return 1

    fixed: list[dict] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        fields = result.get("fields")
        if not isinstance(fields, list):
            continue
        scope_fields = [
            field
            for field in fields
            if isinstance(field, dict) and field.get("fieldCode") == "license_scope"
        ]
        if not scope_fields:
            continue

        # 现值取候选里的第一个 value——和界面显示的是同一个来源
        def current_value(field: dict) -> str:
            candidates = field.get("candidates")
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, dict):
                    return str(first.get("value") or "")
            return str(field.get("value") or "")

        broken = [f for f in scope_fields if not license_scope_text_is_usable(current_value(f))]
        if not broken:
            continue

        fragments = [f for f in (result.get("fragments") or []) if isinstance(f, dict)]
        text_items = [
            (str(f.get("text") or "").strip(), f)
            for f in fragments
            if str(f.get("text") or "").strip()
        ]
        candidate = qualification_scope_candidate(text_items, result)
        new_value = str((candidate or {}).get("text") or "")

        record = {
            "documentId": result.get("documentId"),
            "fileName": result.get("fileName"),
            "旧值": [current_value(f) for f in broken],
            "新值": new_value or "（抽不到，将标为未提取）",
        }
        fixed.append(record)

        if not args.apply:
            continue

        for field in broken:
            if candidate:
                bbox = (candidate.get("fragment") or {}).get("bbox") or field.get("bbox")
                field["candidates"] = [
                    {
                        "value": new_value,
                        "bbox": bbox,
                        "pageNo": field.get("pageNo"),
                        # 说明这一条是重抽来的，不是原始识别结果。
                        # 不留痕的话，以后没人分得清哪些值被脚本动过。
                        "source": "reextract_license_scope",
                    }
                ]
                field["value"] = new_value
            else:
                # 抽不到就明确留空，而不是继续挂着错值
                field["candidates"] = []
                field["value"] = ""
                field["unavailableReason"] = "许可范围未能从表格或标签中提取"

    print(f"检查 {len(results)} 份解析结果，需要重抽 {len(fixed)} 份：")
    for record in fixed:
        print(json.dumps(record, ensure_ascii=False, indent=1))

    if not fixed:
        print("没有需要修的。")
        return 0
    if not args.apply:
        print("\n这是 dry-run，什么都没改。确认后加 --apply。")
        return 0

    # 只刷这一个集合，别顺手把整库重写一遍
    flush_state(selected_state_keys={"ocr_parse_results"})
    print("\n已写回（只刷 ocr_parse_results）。")
    print(
        "注意：审查结论（rule_check_results / review_runs）不会自动更新，"
        "需要对上面这些文档所在的节点重跑 ai-recheck。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
