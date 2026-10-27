#!/usr/bin/env python3
"""Score one node-audit bundle against a confirmed gold answer. Deterministic; no model calls.

Points: each atomic check 2 (exact) / 1 (acceptable alternative; the lenient score counts it 2);
key facts with a frozen `literalMatch` binding score only when one fact matches its name, value, source and page;
key facts without one keep the keyword rule (half when found but not cited to the expected document);
expected conflicts, coverage and tool use 1 each;
a report that passes `node_audit report` validation 2. Critical flags are listed separately because an
inspection assistant that wrongly passes a check, or leaks an ID number, is unusable whatever its score.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

GOLD_SCHEMA = "aicheck-node-audit-gold@1"
SCORE_SCHEMA = "aicheck-node-audit-score@4"
SCRIPT = Path(__file__).resolve().parents[2] / "aicheck-node-audit" / "scripts" / "node_audit.py"


def load_node_audit() -> Any:
    spec = importlib.util.spec_from_file_location("node_audit_for_scoring", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def norm(text: Any) -> str:
    """NFKC (全角→半角, Ⅳ→IV), no whitespace, dates as YYYY-MM-DD, lower case."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"(20\d\d)[年./-](\d{1,2})[月./-](\d{1,2})日?",
                   lambda m: f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", value)
    return value.lower()


def check_text(check: dict[str, Any]) -> str:
    parts: list[Any] = [check.get(k) for k in ("name", "requirement", "reasoning", "reason", "differenceNote")]
    for fact in check.get("facts") or []:
        source = fact.get("source") or {}
        parts += [fact.get("name"), fact.get("value"), source.get("excerpt"), source.get("locator")]
    parts += list(check.get("conflicts") or []) + list(check.get("nextSteps") or [])
    parts += [call.get("summary") if isinstance(call, dict) else str(call) for call in check.get("toolCalls") or []]
    return norm(" ".join(str(p) for p in parts if p))


def report_text(report: dict[str, Any]) -> str:
    parts = [report.get("summary")] + [check_text(c) for c in report.get("checks") or []]
    for key in ("missingMaterials", "relatedNodeSuggestions", "limitations"):
        parts += list(report.get(key) or [])
    # skill 要求把判不了但风险高的事记进 riskFlags；只写在那里的事实也算找到。
    parts += [f"{flag.get('flag') or ''} {flag.get('basis') or ''}" for flag in report.get("riskFlags") or [] if isinstance(flag, dict)]
    return norm(" ".join(str(p) for p in parts if p))


def found(pool: str, any_of: list[list[str]]) -> bool:
    return any(all(norm(token) in pool for token in tokens) for tokens in any_of)


def cited(check: dict[str, Any] | None, cite: str, names: dict[str, str]) -> bool:
    target = norm(cite)
    for fact in (check or {}).get("facts") or []:
        file = str((fact.get("source") or {}).get("file") or "")
        if target in norm(names.get(file, file)):
            return True
    return False


def match_key_fact(expected: dict[str, Any], checks: list[dict[str, Any]], names: dict[str, str], hit: bool) -> dict[str, Any]:
    """Only deterministic literal bindings get automatic credit; no semantic truth claim.

    New isolated criteria can pin literalMatch{name,value,page} plus citeFile. Existing
    answers without this binding remain readable but ambiguous matches require review.
    """
    binding = expected.get("literalMatch") or {}
    result = {"status": "review_required" if hit else "not_found", "cited": False,
              "reason": "关键词命中不能单独证明事实成立或主体角色正确" if hit else "未找到确定性事实"}
    if (not isinstance(binding, dict) or not binding.get("name") or "value" not in binding
            or binding['value'] is None or not str(binding['value']).strip()
            or type(binding.get("page")) is not int or binding['page'] < 1 or not expected.get("citeFile")):
        return result
    value = norm(str(binding['value']))
    target = norm(expected['citeFile'])
    source_paths = [path for path, label in names.items()
                    if target in {norm(path), norm(label), norm(Path(path).name)}]
    uncertain = re.compile(r"无法确认|無法確認|不能确认|不能確認|尚未|未确认|未確認|未识别|未識別|待核|待确认|待確認|不确定|不確定|疑似|可能|并非|並非|不是|cannot\s*confirm|unconfirmed|unknown|not\s*verified|uncertain", re.I)
    matches = []
    for check in checks:
        if check.get("conflicts"):
            continue
        claims = [str(check.get(k) or '') for k in ('reason', 'reasoning', 'differenceNote')]
        if any(value in norm(claim) and uncertain.search(claim) for claim in claims):
            continue
        for fact in check.get('facts') or []:
            source = fact.get('source') or {}
            if norm(fact.get('name')) != norm(binding['name']) or norm(str(fact.get('value'))) != value:
                continue
            if uncertain.search(str(fact.get('name') or '') + ' ' + str(fact.get('value') or '') + ' ' + str(source.get('excerpt') or '')):
                continue
            if source.get('page') == binding['page'] and source_paths == [source.get('file')]:
                matches.append(fact)
    if len(matches) == 1:
        return {'status': 'matched_literal', 'cited': True,
                'reason': '同一条事实的名称、字面值、来源和物理页匹配冻结条件；不证明原图或完整语义正确'}
    if matches:
        result.update(status='review_required', reason='存在多条候选事实，不能自动确定对应关系')
    return result


def clause_token(number: str) -> re.Pattern:
    # OCR may put spaces between label characters. Do not confuse A1 with A10,
    # A1.2, or A1(2). This recognises labels, not the meaning of the requirement.
    return re.compile(r"(?<![a-z0-9.])" + r"\s*".join(re.escape(c) for c in norm(number))
                      + r"(?![a-z0-9.]|\s*[.(])")


def clause_body_present(text: str, number: str) -> bool:
    """Conservative same-page label/body check, including parent + numbered item.

    Block order must be the archived reading order. Never join across pages or
    archives. Unrecognised layouts remain review_required, not a guessed match.
    """
    lines = [line.strip() for line in unicodedata.normalize("NFKC", text).lower().splitlines()
             if line.strip()]
    exact = clause_token(number)
    compound = re.fullmatch(r"(.+)\((\d+)\)", norm(number))
    parent = clause_token(compound[1]) if compound else None
    child = re.compile(r"\(\s*" + re.escape(compound[2]) + r"\s*\)(?!\s*\()") if compound else None
    heading = re.compile(r"^(?:(?:[a-z]\s*)?\d+(?:\s*\.\s*\d+)*(?:\s*\(\s*\d+\s*\))?"
                         r"(?![a-z0-9.])|\(\s*\d+\s*\))")
    contents = re.compile(r"(?:\.{2,}|…+|·{2,})\s*\d+\s*$")

    def body_after(index: int, end: int) -> bool:
        line = lines[index]
        if contents.search(line):
            return False
        tail = line[end:].strip(" :：、;-—")
        if tail:
            return any(c.isalpha() for c in tail)
        # A label on one block/line and its body on the next is common. Stop
        # before a different numbered section; its body cannot fill this gap.
        for following in lines[index + 1:]:
            if heading.match(following) or contents.search(following):
                return False
            if any(c.isalpha() for c in following):
                return True
        return False

    in_parent = False
    for index, line in enumerate(lines):
        match = exact.match(line)
        if match and body_after(index, match.end()):
            return True
        if parent and (match := parent.match(line)):
            in_parent = not bool(contents.search(line))
        elif child and in_parent and (match := child.match(line)):
            if body_after(index, match.end()):
                return True
        elif heading.match(line) and not line.startswith("("):
            in_parent = False
    return False


def standard_evidence(bundle: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Read-only, structural coverage of fixed primary clauses; never a legal/semantic verdict.

    Keep this separate from the historical numeric score. An archived API response can
    establish retrieval and citation, not that the model understood it. Local PDF citations
    are a supported route, but this bundle-only check cannot prove which images were viewed.
    """
    rows, warnings = [], []
    try:
        rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
        clauses = rules["standardClauses"]
        if not isinstance(clauses, list) or any(not isinstance(c, dict) for c in clauses):
            raise ValueError("invalid standardClauses")
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "review_required", "rows": [], "warnings": ["固定条款清单缺失或不可读"]}
    records = []
    for path in sorted((bundle / "tool-results").glob("*-standard-content.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("invalid record")
            records.append((str(path.relative_to(bundle)), record))
        except (OSError, ValueError):
            warnings.append(f"标准原文存档不可读：{path.name}")
    sources = [f["source"] for c in report.get("checks") or [] for f in c.get("facts") or []
               if isinstance(f.get("source"), dict)]
    for clause in clauses:
        if clause.get("bindingRole") != "primary":
            continue
        row = {k: clause.get(k) for k in ("standardRef", "clauseNo", "sourcePage")}
        row.update(status="not_recorded", archives=[])
        rows.append(row)
        ref, number, page, file_id = (clause.get(k) for k in ("standardRef", "clauseNo", "sourcePage", "knowledgeFileId"))
        if clause.get("applicability") != "always" or not ref or not number or not isinstance(page, int) or page < 1:
            row["status"] = "applicability_review"
            continue
        token = clause_token(number)
        def has_clause(text: Any) -> bool:
            return bool(token.search(unicodedata.normalize("NFKC", str(text or "")).lower()))
        api_sources = [s for s in sources if s.get("file") == "tool:standard-content" and s.get("page") in (None, page)
                       and has_clause(s.get("locator"))]
        local_ref = re.sub(r"[^a-z0-9]", "", norm(ref).removeprefix("std-"))
        local = [s for s in sources if str(s.get("file", "")).startswith("standard:") and s.get("page") == page
                 and local_ref and local_ref in re.sub(r"[^a-z0-9]", "", norm(s.get("file")))
                 and has_clause(str(s.get("excerpt") or "") + " " + str(s.get("locator") or ""))]
        candidates, retrieved, cited_archives = [], [], []
        for relative, record in records:
            args = record.get("arguments") or {}
            result = record.get("result") or {}
            if not isinstance(args, dict) or not isinstance(result, dict):
                warnings.append(f"标准原文存档结构不可读：{relative}")
                continue
            if record.get("tool") != "standard-content" or not file_id or args.get("file_id") != file_id:
                continue
            if args.get("page_no") not in (None, page):
                continue
            parent_match = re.fullmatch(r"(.+)\(\d+\)", norm(number))
            allowed_sections = {norm(number)} | ({parent_match[1]} if parent_match else set())
            if args.get("section") and norm(args["section"]) not in allowed_sections:
                continue
            candidates.append(record)
            row["archives"].append(relative)
            if record.get("ok") is not True or result.get("knowledgeFileId") != file_id:
                continue
            selection = result.get("selection") or {}
            if not isinstance(selection, dict) or selection.get("contentFound") is False:
                continue
            blocks = result.get("blocks") or []
            if not isinstance(blocks, list):
                warnings.append(f"标准正文结构不可读：{relative}")
                continue
            body = "\n".join(str(b.get("text") or "") for b in blocks
                            if isinstance(b, dict) and b.get("pageNo") == page)
            if not clause_body_present(body, number):
                continue
            retrieved.append(relative)
            # Exact path boundary: a citation to x.json.backup is not a citation to x.json.
            path_token = re.compile(r"(?<![\w./-])" + re.escape(relative) + r"(?![\w./-])")
            if any(path_token.search(str(s.get("locator") or "")) for s in api_sources):
                cited_archives.append(relative)
        if cited_archives:
            row.update(status="documented", archives=cited_archives)
        elif local:
            row["status"] = "local_citation_review"
        elif retrieved:
            row["status"] = "retrieved_uncited"
        elif candidates:
            row["status"] = "retrieval_failed" if all(r.get("ok") is False for r in candidates) else "content_unverified"
        elif api_sources:
            row["status"] = "unbacked_citation"
    status = "review_required" if warnings or any(r["status"] != "documented" for r in rows) else "complete" if rows else "not_required"
    return {"status": status, "rows": rows, "warnings": warnings}


def score(gold: dict[str, Any], bundle: Path) -> dict[str, Any]:
    if gold.get("schemaVersion") != GOLD_SCHEMA:
        raise SystemExit(f"gold schemaVersion 应为 {GOLD_SCHEMA}")
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    report_path = bundle / "audit.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"checks": []}
    names = {f["path"]: f.get("fileName") or f["path"] for f in manifest.get("files") or []}
    checks = {c.get("atomicCheckId"): c for c in report.get("checks") or []}
    critical: list[str] = []
    points = maximum = 0.0
    rows: dict[str, list[dict[str, Any]]] = {"verdicts": [], "keyFacts": [], "extras": []}

    for cid, expected in gold["checks"].items():
        got = (checks.get(cid) or {}).get("verdict")
        gained = 2.0 if got == expected["verdict"] else 1.0 if got in expected.get("accept", []) else 0.0
        if got == "passed" and expected["verdict"] != "passed" and "passed" not in expected.get("accept", []):
            critical.append(f"误判符合 {cid}（标准：{expected['verdict']}）")
        if got == "failed" and expected["verdict"] != "failed" and "failed" not in expected.get("accept", []):
            critical.append(f"误判不符合 {cid}（标准：{expected['verdict']}）")
        points, maximum = points + gained, maximum + 2
        rows["verdicts"].append({"check": cid, "gold": expected["verdict"], "got": got, "points": gained, "max": 2})

    whole = report_text(report)
    for fact in gold.get("keyFacts") or []:
        where = fact.get("where", "anywhere")
        check = checks.get(where)
        if where == "anywhere":
            pool = whole
        elif where == "missingMaterials":
            pool = norm(" ".join(report.get("missingMaterials") or []))
        else:
            pool = check_text(check) if check else ""
        hit = found(pool, fact["anyOf"])
        cite_from = list(checks.values()) if where in ("anywhere", "missingMaterials") else [check]
        weight = float(fact.get("weight", 1))
        if fact.get("literalMatch"):
            # 冻结了字面绑定的事实：同一条事实的名称、值、出处、页码都对上才计分，关键词命中不算。
            matching = match_key_fact(fact, [c for c in cite_from if c], names, hit)
            got_it = matching["status"] == "matched_literal"
            gained = weight if got_it else 0.0
        else:
            # 没有字面绑定的旧答案：关键词命中给一半，引对文件给满分；不限检查项的事实任一检查引了该文件就算。
            cite_ok = hit and (not fact.get("citeFile") or any(cited(c, fact["citeFile"], names) for c in cite_from))
            matching = {"status": "keyword_cited" if cite_ok else "keyword_only" if hit else "not_found", "cited": bool(cite_ok)}
            got_it = hit
            gained = weight if cite_ok else weight / 2 if hit else 0.0
        points, maximum = points + gained, maximum + weight
        rows["keyFacts"].append({"id": fact["id"], "desc": fact["desc"], "where": where, "keywordHit": hit,
                                 **matching, "found": got_it, "points": gained, "max": weight})

    for cid in gold.get("expectConflicts") or []:
        ok = bool((checks.get(cid) or {}).get("conflicts"))
        points, maximum = points + ok, maximum + 1
        rows["extras"].append({"item": f"{cid} 记录冲突", "ok": ok})
    for cid, expected in (gold.get("coverage") or {}).items():
        cov = (checks.get(cid) or {}).get("coverage") or {}
        ok = cov.get("items") == expected["items"] and cov.get("checked") == expected["items"]
        points, maximum = points + ok, maximum + 1
        rows["extras"].append({"item": f"{cid} 逐件覆盖 {expected['items']}", "ok": ok})
    saved_tools = sorted((bundle / "tool-results").glob("*.json")) if (bundle / "tool-results").is_dir() else []
    for tool in gold.get("toolsUsed") or []:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in saved_tools if p.name.endswith(f"-{tool}.json")]
        succeeded = any(r.get("ok", "error" not in r) for r in records)
        # 平台不可用时查了并存档失败结果算一半：不是 skill 的错，但结论确实少了一道核验。
        gained = 1.0 if succeeded else 0.5 if records else 0.0
        points, maximum = points + gained, maximum + 1
        rows["extras"].append({"item": f"调用并存档 {tool}" + ("" if succeeded or not records else "（调用失败已存档）"), "ok": succeeded})

    raw = json.dumps(report, ensure_ascii=False)
    if (bundle / "audit.md").exists():
        raw += (bundle / "audit.md").read_text(encoding="utf-8")
    node_audit = load_node_audit()
    for rule in gold.get("forbiddenPatterns") or []:
        hit = node_audit.contains_id_number(raw) if rule.get("validator") == "id_number" else re.search(rule["regex"], raw)
        if hit:
            critical.append(f"{rule['desc']}（{rule['id']}）")

    try:
        _, _, errors, _ = node_audit.check_report(bundle)
    except Exception as exc:  # noqa: BLE001 -- a missing or broken report scores zero here
        errors = [f"{type(exc).__name__}: {exc}"]
    valid = not errors
    points, maximum = points + 2 * valid, maximum + 2
    rows["extras"].append({"item": "报告通过 node_audit 校验", "ok": valid, "errors": errors[:10]})
    if not valid:
        critical.append(f"报告未通过校验（{len(errors)} 条错误）")

    evidence = standard_evidence(bundle, report)
    percent = round(100 * points / maximum, 1) if maximum else 0.0
    # 宽松分：gold 也接受的另一种结论算满分。两种结论都对时追着首选结论改 skill 就是过拟合，判断有没有审错看这个分。
    lenient = points + sum(r["max"] - r["points"] for r in rows["verdicts"] if 0 < r["points"] < r["max"])
    lenient_percent = round(100 * lenient / maximum, 1) if maximum else 0.0
    needs_review = any(r['status'] == 'review_required' for r in rows['keyFacts'])
    return {"schemaVersion": SCORE_SCHEMA, "gold": gold["id"], "bundle": str(bundle), "points": points, "max": maximum,
            "percent": percent, "lenientPoints": lenient, "lenientPercent": lenient_percent, "critical": critical, "standardEvidence": evidence,
            "factReviewRequired": needs_review,
            "scoringScope": "literal bindings where the gold has them, keywords elsewhere; not semantic or visual adjudication",
            "all_pass": percent >= 85 and not critical and not needs_review and evidence["status"] in {"complete", "not_required"}, **rows}


def markdown(result: dict[str, Any]) -> str:
    lines = [f"## {result['gold']}：{result['points']:g}/{result['max']:g}（{result['percent']}%；宽松 {result['lenientPercent']}%）", ""]
    lines += [f"- ❗ {c}" for c in result["critical"]] or ["- 无严重问题"]
    lines += ["", "| 检查 | 标准 | 本次 | 得分 |", "|---|---|---|---|"]
    lines += [f"| {r['check']} | {r['gold']} | {r['got'] or '—'} | {r['points']:g}/{r['max']} |" for r in result["verdicts"]]
    lines += ["", "| 关键事实 | 位置 | 找到 | 引对出处 | 得分 |", "|---|---|---|---|---|"]
    lines += [f"| {r['id']} {r['desc']} | {r['where']} | {'是' if r['found'] else '否'} | {'是' if r['cited'] else '否'} | "
              f"{r['points']:g}/{r['max']:g} |" for r in result["keyFacts"]]
    lines += ["", "| 其他 | 结果 |", "|---|---|"] + [f"| {r['item']} | {'是' if r['ok'] else '否'} |" for r in result["extras"]]
    evidence = result["standardEvidence"]
    lines += ["", f"固定主条款取证：{evidence['status']}；综合验收：{'通过' if result['all_pass'] else '未通过或待覆核'}。",
              f"事实待裁定：{result['factReviewRequired']}。答案里带 literalMatch 的事实要名称、字面值、来源、页码同条对上才计分；"
              "其余沿用关键词＋引对文件口径，与旧分数可比。",
              "仅检查已存档原文和报告引用的对应关系，不证明条款理解正确；本地 PDF 引用需核对看图轨迹。"]
    lines += [f"- {r['standardRef']} {r['clauseNo']}：{r['status']}" for r in evidence["rows"]]
    lines += [f"- {warning}" for warning in evidence["warnings"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按标准答案给节点审计资料包打分")
    parser.add_argument("--gold", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--md", action="store_true", help="输出 Markdown 表，默认 JSON")
    args = parser.parse_args(argv)
    gold = json.loads(Path(args.gold).expanduser().read_text(encoding="utf-8"))
    result = score(gold, Path(args.bundle).expanduser().resolve())
    print(markdown(result) if args.md else json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
