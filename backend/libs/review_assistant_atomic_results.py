"""AI 审查助手的原子项结论：只认正式复核留痕，和节点页同一个来源。

## 2026-11-09 生产实测

测试项目3（P-2026-ECD202）节点 1「设计单位许可资质」。正式复核 RRUN-B0C1A8F9EB
（11-03，业务包 2026.09.23）留痕：AC-R01-01/02/04 通过；AC-R01-03（施工期只录在项目信息里，
节点资料里没有出处）、AC-R01-05（证据追溯要等 03）证据不足。节点页显示的就是这一份。
同样的资料，助手前后两次说法相反：

- 23:20 只调了 assemble_node_judgment_facts、check_design_license_scope、verify_org_license
  三个单项工具，回答末尾自己补了一句「无证据不足原子项」。进模型的上下文里只有 findingDrafts，
  没有逐项结论；用户偏好又要求「列出证据不足的原子项编号」，模型就编了一个总括。
- 23:25 新会话调 run_node_formal_judgment，五项全部证据不足，模型解释成「绑定未发布（draft）」。

## 根因

1. run_node_formal_judgment 不读留痕，在对话里自己重跑工具计划，却没带正式链装配的
   evidenceFacts / evidenceRefs（execution.py 从 businessFacts.judgment 取）。
   validate_evidence_grounding 拿到空事实，每个原子项都过不了锚定门 → 全部证据不足。
2. 它的提示只看 bindingSet.lifecycleStatus。生产上整个绑定集就是 draft，R01 在 pilotRules 里，
   正式复核正是凭试点放行的；提示却写「draft（未发布），结果仅供参考」，
   模型据此把五项证据不足归因于 draft——和真实原因（缺锚定事实）无关。
3. 回答落定前没有任何核对：模型写什么，界面就显示什么。

## 现在的做法

- formal_snapshot()：从这次复核的 rule_check_results 按 output_contract.atomic_check_outcomes
  取逐项结论。节点页用的就是这个函数（output_contract.review_view_with_limitations），不另算。
- 每次提问都放进上下文（formalAtomicResults）；run_node_formal_judgment 有留痕时直接返回留痕，
  没有留痕才在对话内临时重跑，并写明「不是节点结论」（advisory_rerun_notices）。
- reconcile_answer()：回答落定前核对。正文里某个 AC 编号写的结论与留痕不同、说「无证据不足」
  而留痕里有证据不足、说「全部证据不足」而留痕不是，或者列了原子项却漏了未通过项，
  就在正文后追加更正并照录留痕结论。模型可以解释，不可以改判。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from libs.review_orchestrator import output_contract

RESULT_LABELS = {
    "passed": "符合",
    "failed": "不符合",
    "evidence_insufficient": "证据不足",
    "not_applicable": "不适用",
    "human_review_required": "需人工判断",
    "execution_error": "执行故障",
}
_NOT_PASSED = ("failed", "evidence_insufficient", "human_review_required", "execution_error")

# 原因码的说法与前端 auditLabels.ts 一致；没收录的照原样给，模型照抄编号也比编一句强。
_REASON_LABELS = {
    "construction_period_not_in_node_documents": "施工期只录在项目信息里、本节点资料里没有出处，不能据此判符合",
    "business_failed_without_grounded_facts": "业务工具已发现不符合项，但这些事实还没有页码和引文可核，需人工确认",
    "provider_confidence_unavailable": "抽取引擎没给置信度，需人工核对引文",
}


def _reason_text(outcome: dict[str, Any], atomic: dict[str, Any]) -> str:
    codes = [str(outcome.get("reason") or ""), *[str(item) for item in atomic.get("warnings") or []]]
    texts: list[str] = []
    for code in codes:
        if not code:
            continue
        if code.startswith("evidence_trace_waits_for:"):
            text = f"证据追溯要等 {code.split(':', 1)[1]} 先有结论"
        else:
            text = _REASON_LABELS.get(code, code)
        if text not in texts:
            texts.append(text)
    return "；".join(texts)[:200]


def _evidence_change(run: dict[str, Any], evidence_links: Iterable[dict[str, Any]]) -> dict[str, int] | None:
    """复核之后节点资料有没有变：只比文档版本，被驳回的不算（正式复核也不收）。"""
    used = {str(item) for item in run.get("inputDocumentVersionIds") or [] if item}
    if not used:
        return None
    current = {
        str(item.get("documentVersionId"))
        for item in evidence_links
        if isinstance(item, dict)
        and item.get("documentVersionId")
        and str(item.get("manualStatus") or "").lower() != "rejected"
    }
    added, removed = len(current - used), len(used - current)
    return {"added": added, "removed": removed} if added or removed else None


def formal_snapshot(
    state: dict[str, Any],
    review_run: dict[str, Any] | None,
    *,
    evidence_links: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """当前复核的逐项结论（与节点页同源）。没有复核或没有留痕时 available=False。"""
    run = review_run or {}
    run_id = str(run.get("reviewRunId") or run.get("id") or "")
    if not run_id:
        return {
            "available": False,
            "reason": "no_review_run",
            "notice": "本节点还没有复核记录，没有原子项结论；不得自拟原子项结论，需要时请发起正式 AI 复核。",
        }
    records = output_contract.run_check_records(run, state)
    outcomes = output_contract.atomic_check_outcomes(records, run)
    if not outcomes:
        return {
            "available": False,
            "reason": "no_recorded_atomic_results",
            "reviewRunId": run_id,
            "runStatus": run.get("status"),
            "notice": "当前复核没有原子项结论留痕（可能还在执行、执行失败或只做了缺项预审）；不得自拟原子项结论。",
        }
    raw = {
        str(atomic.get("atomicCheckId") or ""): atomic
        for record in records
        for atomic in record.get("atomicCheckResults") or []
        if isinstance(atomic, dict)
    }
    items = []
    for outcome in outcomes:
        result = str(outcome.get("result") or "")
        item = {
            "atomicCheckId": outcome["atomicCheckId"],
            "name": outcome.get("name") or outcome["atomicCheckId"],
            "result": result,
            "resultLabel": RESULT_LABELS.get(result, result or "未知"),
        }
        if result != "passed":
            reason = _reason_text(outcome, raw.get(outcome["atomicCheckId"]) or {})
            failed_checks = [str(check.get("code")) for check in outcome.get("checks") or [] if check.get("passed") is False]
            item.update({key: value for key, value in (("reason", reason), ("failedChecks", failed_checks[:6])) if value})
        items.append(item)
    changed = _evidence_change(run, evidence_links)
    snapshot = {
        "available": True,
        "source": "formal_review_run",
        "matchesNodePage": True,
        "reviewRunId": run_id,
        "reviewMode": run.get("reviewMode"),
        "runStatus": run.get("status"),
        "runCreatedAt": run.get("createdAt"),
        "nodeResult": next((str(record.get("result")) for record in records if record.get("result")), None),
        "counts": dict(Counter(item["result"] for item in items)),
        "items": items,
        "notice": "这是本节点复核留痕的逐项结论，与节点页一致；回答须照录，不得改判。",
    }
    if changed:
        snapshot["evidenceChangedSinceRun"] = changed
        snapshot["notice"] += (
            f"复核之后节点资料有变动（新增 {changed['added']} 份、移除 {changed['removed']} 份），"
            "留痕对应复核时的资料；要按现有资料判定，请建议重新发起正式复核。"
        )
    return snapshot


def recorded_tool_output(
    state: dict[str, Any],
    review_run: dict[str, Any] | None,
    *,
    evidence_links: Iterable[dict[str, Any]] = (),
) -> dict[str, Any] | None:
    """run_node_formal_judgment 有留痕时的返回：直接给留痕，不在对话里重跑。没有留痕返回 None。"""
    snapshot = formal_snapshot(state, review_run, evidence_links=evidence_links)
    if not snapshot.get("available"):
        return None
    counts = snapshot["counts"]
    rule_ids = sorted({item["atomicCheckId"].split("-")[1] for item in snapshot["items"] if item["atomicCheckId"].count("-") >= 2})
    return {
        "status": "succeeded",
        "source": "formal_review_run",
        "advisory": False,
        "reviewRunId": snapshot["reviewRunId"],
        "sourceRuleId": "/".join(rule_ids) or None,
        "result": snapshot["nodeResult"],
        "summary": {
            "atomicCheckCount": len(snapshot["items"]),
            "passedCount": counts.get("passed", 0),
            "failedCount": counts.get("failed", 0),
            "evidenceInsufficientCount": counts.get("evidence_insufficient", 0),
        },
        "atomicResults": snapshot["items"],
        **({"evidenceChangedSinceRun": snapshot["evidenceChangedSinceRun"]} if snapshot.get("evidenceChangedSinceRun") else {}),
        "notice": snapshot["notice"],
    }


def advisory_rerun_notices(binding_set: dict[str, Any], source_rule_id: str, *, has_facts: bool) -> list[str]:
    """对话内临时重跑（没有复核留痕时）的说明。

    只看 lifecycleStatus 会说错：生产上整个绑定集是 draft，节点规则在 pilotRules 里时
    正式复核照样放行。把「draft」当原因告诉模型，它就会把证据不足归因于 draft。
    """
    notices = [
        (
            "本节点当前复核没有原子项留痕，这是对话内的临时重跑，不是节点结论，"
            "未经过正式复核的取证与锚定步骤，证据不足项可能只是缺少锚定事实；节点结论以正式 AI 复核为准。"
        )
    ]
    lifecycle = str(binding_set.get("lifecycleStatus") or "draft").lower()
    pilot_rules = {str(item) for item in binding_set.get("pilotRules") or [] if item}
    if lifecycle != "published" and source_rule_id not in pilot_rules:
        notices.append(f"原子项工具绑定为 {lifecycle} 状态且本规则未列入试点，正式复核也不会放行。")
    if not has_facts:
        notices.append("该节点暂无事实装配器，判定主要依赖绑定参数与证据文档，缺失事实按证据不足处理。")
    return notices


def grounding_inputs(facts: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """与正式链同一处取锚定事实：businessFacts.judgment 的 claimedFacts / evidenceRefs。"""
    judgment = facts.get("judgment") if isinstance(facts.get("judgment"), dict) else {}
    claimed = [item for item in judgment.get("claimedFacts") or [] if isinstance(item, dict)]
    refs = [item for item in judgment.get("evidenceRefs") or [] if isinstance(item, dict)]
    return claimed, refs


def model_view(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """进模型上下文的那份：去掉只给系统用的字段。"""
    if not snapshot:
        return {"available": False, "notice": "未取得复核留痕；不得自拟原子项结论。"}
    return {key: value for key, value in snapshot.items() if key not in {"matchesNodePage"}}


# ---- 回答核对 ----

# AC-R01-01，以及模型常写的简写 AC-R01-01/02/04、AC-R01-01、02、04
_ATOMIC_ID = re.compile(r"AC-R(\d{2})-(\d{2})((?:\s*[/、,，及和]\s*\d{2}(?!\d))*)")
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
# 顺序要紧：先认长的，「不符合」里有「符合」，「未通过」里有「通过」
_LABEL_PATTERNS = (
    ("evidence_insufficient", re.compile(r"证据不足|evidence_insufficient")),
    ("failed", re.compile(r"不符合|不通过|未通过|不合格|failed")),
    ("human_review_required", re.compile(r"需人工判断|需要人工判断|human_review_required")),
    ("not_applicable", re.compile(r"不适用|not_applicable")),
    ("passed", re.compile(r"符合|通过|合格|passed")),
)
# 总括说法只认这几种句式。「无」字太常见（「无施工期出处，证据不足」），宽了就是误报。
_ITEM = r"(?:原子项|核查项|项)"
_NONE = r"(?:无|没有|不存在|未见|未发现)(?:任何)?"
# 「原子项」与「全部/均」之间不许夹编号或顿号：「原子项 03、05 均证据不足」说的是部分
_GAP = r"[^。\n；;，,、/\d]{0,6}"
_ALL = rf"(?:(?:原子项|核查项|各项){_GAP}(?:全部|均|都|一律)|(?:全部|所有)(?:原子项|核查项))"
_BLANKET = (
    # 「无证据不足原子项」「没有证据不足的项」「证据不足的原子项：无」
    ("no_insufficient", re.compile(rf"{_NONE}证据不足的?{_ITEM}|证据不足的?{_ITEM}[：:]\s*(?:无|没有)")),
    ("no_failed", re.compile(rf"{_NONE}不符合的?{_ITEM}|不符合的?{_ITEM}[：:]\s*(?:无|没有)")),
    # 「5 个原子项均证据不足」「全部原子项证据不足」
    ("all_insufficient", re.compile(rf"{_ALL}{_GAP}证据不足")),
    ("all_passed", re.compile(rf"{_ALL}[^。\n；;，,不未]{{0,4}}(?:符合|通过)")),
)
# 「其余原子项均符合」说的是剩下的那些，不是总括
_PARTIAL_HINTS = ("其余", "其他", "剩余", "另外", "除", "以外", "之外")


def _ids_in(line: str) -> list[str]:
    ids: list[str] = []
    for match in _ATOMIC_ID.finditer(line):
        rule, first, tail = match.groups()
        for number in [first, *re.findall(r"\d{2}", tail or "")]:
            ids.append(f"AC-R{rule}-{number}")
    return ids


def _labels_in(text: str) -> set[str]:
    found: set[str] = set()
    for result, pattern in _LABEL_PATTERNS:
        if pattern.search(text):
            found.add(result)
            text = pattern.sub(" ", text)
    return found


def _blanket_conflicts(text: str, counts: dict[str, int], total: int) -> list[dict[str, Any]]:
    conflicts = []
    for kind, pattern in _BLANKET:
        match = pattern.search(text)
        if not match:
            continue
        sentence_start = max(text.rfind(mark, 0, match.start()) for mark in ("。", "\n", "；", ";", "|"))
        if kind.startswith("all_") and any(hint in text[sentence_start + 1 : match.end()] for hint in _PARTIAL_HINTS):
            continue
        wrong = (
            (kind == "no_insufficient" and counts.get("evidence_insufficient", 0) > 0)
            or (kind == "no_failed" and counts.get("failed", 0) > 0)
            or (kind == "all_insufficient" and counts.get("evidence_insufficient", 0) < total)
            or (kind == "all_passed" and any(counts.get(result, 0) for result in _NOT_PASSED))
        )
        if wrong:
            conflicts.append({"kind": kind, "quote": match.group(0)[:40]})
    return conflicts


def _correction(snapshot: dict[str, Any], mismatches: list[dict[str, Any]], omitted: list[str]) -> str:
    lines = ["", "---"]
    if mismatches:
        problems = []
        for item in mismatches[:6]:
            if item.get("atomicCheckId"):
                problems.append(f"{item['atomicCheckId']} 上文写作“{item['stated']}”，留痕为“{item['recorded']}”")
            else:
                problems.append(f"“{item['quote']}”与留痕不符")
        lines.append("**以复核留痕为准**：上文与节点页的原子项结论不一致（" + "；".join(problems) + "）。")
    elif omitted:
        lines.append(f"**补充**：上文没有提到以下未通过的原子项（{'、'.join(omitted)}）。")
    created = str(snapshot.get("runCreatedAt") or "")[:16]
    lines.append(f"复核 {snapshot.get('reviewRunId')}{f'（{created}）' if created else ''}逐项结论（与节点页一致）：")
    for item in snapshot.get("items") or []:
        reason = f"（{item['reason']}）" if item.get("reason") else ""
        name = f" {item['name']}" if item.get("name") and item["name"] != item["atomicCheckId"] else ""
        lines.append(f"- {item['atomicCheckId']}{name}：{item['resultLabel']}{reason}")
    if snapshot.get("evidenceChangedSinceRun"):
        lines.append("复核之后节点资料有变动，要按现有资料判定请重新发起正式 AI 复核。")
    return "\n".join(lines)


def reconcile_answer(text: str | None, snapshot: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    """回答与留痕逐项核对；不一致就在正文后追加更正。返回（正文, 核对记录）。"""
    if not text or not snapshot:
        return text, None
    if not snapshot.get("available"):
        claims = [kind for kind, pattern in _BLANKET if pattern.search(text)]
        if not claims:
            return text, None  # 没有留痕、也没说原子项：没什么可核的，不往执行记录里塞空话
        note = "\n\n---\n**说明**：本节点当前复核没有原子项结论留痕，上文关于原子项的总括说法未经正式复核，不能作为节点结论。"
        return text + note, {"status": "unsupported_claim", "claims": claims, "reason": snapshot.get("reason")}
    recorded = {item["atomicCheckId"]: item for item in snapshot.get("items") or []}
    plain = _LINK_TARGET.sub("]", text)
    mismatches: list[dict[str, Any]] = []
    mentioned: set[str] = set()
    for line in plain.splitlines():
        ids = _ids_in(line)
        mentioned.update(ids)
        if not ids:
            continue
        labels = _labels_in(_ATOMIC_ID.sub(" ", line))
        if len(labels) != 1:
            continue  # 没写结论或一行里有几种说法：不猜
        stated = next(iter(labels))
        for check_id in ids:
            item = recorded.get(check_id)
            if item and item["result"] != stated:
                mismatches.append({"atomicCheckId": check_id, "stated": RESULT_LABELS.get(stated, stated),
                                   "recorded": item["resultLabel"]})
    counts = snapshot.get("counts") or {}
    mismatches += _blanket_conflicts(plain, counts, len(recorded))
    not_passed = [check_id for check_id, item in recorded.items() if item["result"] in _NOT_PASSED]
    omitted = [check_id for check_id in not_passed if check_id not in mentioned] if mentioned else []
    check = {"status": "consistent", "reviewRunId": snapshot.get("reviewRunId")}
    if not mismatches and not omitted:
        return text, check
    check.update({"status": "corrected" if mismatches else "completed_omissions",
                  "mismatches": mismatches[:12], "omitted": omitted})
    return text + "\n" + _correction(snapshot, mismatches, omitted), check
