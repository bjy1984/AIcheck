"""系统使用教程检索：AI 助手回答「这个按钮是什么、下一步怎么做」这类问题的依据。

## 为什么不放进「知识库」

知识库（apps/api/knowledge_admin_routes.py）是管理员维护的标准条款库：入库要走 OCR、切片、
向量化流水线，切片按固定长度而不是按标题，而且检索结果会进审查依据——教程混进去会污染
标准依据。这里改用仓库里的 markdown：随版本发布、改教程就是改文件、不依赖向量服务。

## 检索

纯词法。中文没有空格，knowledge_retrieval.query_tokens 把连续汉字切成最长 4 个字一段，
“怎么退回补正”切出来的“怎么退回”在任何教程里都不会出现；所以这里自己按相邻两字（bigram）
建索引：问句和小节都切成两字组，命中的两字组按逆文档频率加权，标题和关键词里命中的再加三倍。

问句先按虚词（“怎么”“什么”“吗”…）断开再切，免得虚词和相邻的字拼出假的两字组。

## 文件约定

见 docs/_README.md。`inspection_*.md` 只给监检角色，`common_*.md` 所有角色。
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DOCS_DIR = Path(__file__).parent / "docs"

# 一节教程返回给模型的最大字数。教程小节本来就按「一节讲一件事」写，超长的多半是写法问题，截断保护 token。
MAX_SECTION_CHARS = 1200
DEFAULT_TOP_K = 3
# 其余结果的分数不到第一名的这个比例就不返回：凑够条数比少返回两条更容易让模型拿无关的小节作答。
RELATIVE_SCORE_FLOOR = 0.4
HEADING_WEIGHT = 3.0

_CJK_RUN = re.compile(r"[一-鿿]+")
_LATIN_WORD = re.compile(r"[a-z0-9]+")
# 虚词和疑问词：只用来把问句断开，本身不进索引。不含“不”“能”“可”——它们出现在“不适用”“可以”这类要紧的词里。
_BREAK_CHARS = set("的了吗呢啊吧是在有和与或我你它这那个请问怎么怎样如何什么")
_KEYWORD_LINE = "关键词："
_ROLE_COMMON = "common"


@dataclass(frozen=True)
class HelpSection:
    doc_id: str
    doc_title: str
    heading: str
    body: str
    role: str
    heading_terms: frozenset[str]
    body_terms: frozenset[str]

    @property
    def path_label(self) -> str:
        return f"《{self.doc_title}》{self.heading}"


def _terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    terms: set[str] = set()
    for word in _LATIN_WORD.findall(normalized):
        if len(word) >= 2:
            terms.add(word)
    for run in _CJK_RUN.findall(normalized):
        piece: list[str] = []
        for char in run + "\0":
            if char in _BREAK_CHARS or char == "\0":
                terms.update("".join(piece[i : i + 2]) for i in range(len(piece) - 1))
                piece = []
            else:
                piece.append(char)
    return terms


def _parse_document(path: Path) -> list[HelpSection]:
    stem = path.stem
    role = stem.split("_", 1)[0]
    lines = path.read_text(encoding="utf-8").splitlines()
    doc_title = stem
    sections: list[HelpSection] = []
    heading: str | None = None
    body_lines: list[str] = []
    keywords: list[str] = []

    def flush() -> None:
        if heading is None:
            return
        body = "\n".join(body_lines).strip()
        if not body:
            return
        sections.append(
            HelpSection(
                doc_id=stem,
                doc_title=doc_title,
                heading=heading,
                body=body,
                role=role,
                heading_terms=frozenset(_terms(" ".join([heading, *keywords]))),
                body_terms=frozenset(_terms(body)),
            )
        )

    for line in lines:
        if line.startswith("# ") and heading is None:
            doc_title = line[2:].strip() or stem
        elif line.startswith("## "):
            flush()
            heading, body_lines, keywords = line[3:].strip(), [], []
        elif heading is not None:
            if line.startswith(_KEYWORD_LINE) and not body_lines:
                keywords = [item for item in re.split(r"[、,，;；\s]+", line[len(_KEYWORD_LINE) :]) if item]
            else:
                body_lines.append(line)
    flush()
    return sections


@lru_cache(maxsize=1)
def load_sections() -> tuple[HelpSection, ...]:
    """读全部教程并按二级标题切成小节。`_` 开头的文件是写给维护者看的说明，不检索。"""
    sections: list[HelpSection] = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        if path.name.startswith("_"):
            continue
        sections.extend(_parse_document(path))
    return tuple(sections)


def _visible(section: HelpSection, role: str) -> bool:
    return section.role in {role, _ROLE_COMMON}


def search_help_sections(query: str, *, role: str = "inspection", top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    query_terms = _terms(query)
    if not query_terms:
        return []
    sections = [item for item in load_sections() if _visible(item, role)]
    if not sections:
        return []
    total = len(sections)
    document_frequency = {
        term: sum(1 for item in sections if term in item.heading_terms or term in item.body_terms)
        for term in query_terms
    }
    scored: list[tuple[float, int, HelpSection]] = []
    for item in sections:
        score = 0.0
        matched = 0
        for term in query_terms:
            in_heading = term in item.heading_terms
            if not in_heading and term not in item.body_terms:
                continue
            matched += 1
            score += math.log(1 + total / (1 + document_frequency[term])) * (HEADING_WEIGHT if in_heading else 1.0)
        # 问句只有一两个词时命中一个就够；更长的问句至少命中两个，免得单个常见词把无关小节带出来。
        if matched >= min(2, len(query_terms)):
            scored.append((score, matched, item))
    scored.sort(key=lambda entry: (-entry[0], -entry[1], entry[2].doc_id, entry[2].heading))
    if not scored:
        return []
    floor = scored[0][0] * RELATIVE_SCORE_FLOOR
    results: list[dict[str, Any]] = []
    for score, _matched, item in scored:
        if score < floor or len(results) >= max(1, top_k):
            break
        text = item.body if len(item.body) <= MAX_SECTION_CHARS else item.body[:MAX_SECTION_CHARS] + "…"
        results.append(
            {
                "source": item.path_label,
                "docId": item.doc_id,
                "heading": item.heading,
                "text": text,
                "score": round(score, 2),
            }
        )
    return results


# 注册给对话 Agent 的工具说明。描述里写清楚「什么时候调用、什么时候不调用」：
# 模型最容易犯的错是拿它去回答审查结论，或者拿审查类工具去回答“按钮在哪”。
TOOL_NAME = "search_help_docs"
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "检索本系统的使用教程（页面入口、按钮和状态的含义、操作步骤、常见问题）。"
            "用户问“怎么用、在哪里、是什么意思、下一步怎么做、为什么点不了”这类系统用法问题时调用。"
            "不要用它回答具体节点的审查结论、证据或标准条款。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户问题里的关键说法，例如“退回补正怎么操作”。"}
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


def search_help_docs_tool(arguments: dict[str, Any] | None, *, role: str = "inspection") -> dict[str, Any]:
    query = str((arguments or {}).get("query") or "").strip()
    if not query:
        return {"status": "rejected", "errorCode": "HELP_QUERY_REQUIRED", "message": "请提供要检索的问题。"}
    sections = search_help_sections(query, role=role)
    return {
        "status": "succeeded",
        "sectionCount": len(sections),
        "sections": sections,
        # 没命中也要明说，让模型如实告诉用户“教程里没有”，而不是凭印象编一个页面。
        "note": (
            "仅依据 sections 里的教程内容回答，并写明出自哪一节。"
            if sections
            else "教程里没有找到相关内容：请如实告诉用户教程里没有，不要编造页面、按钮或步骤。"
        ),
    }
