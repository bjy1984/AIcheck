"""Page-local title evidence for compound documents; never infer unlabelled continuation pages."""
import re
from copy import deepcopy

TITLES = {
    "pqr": (r"焊接工艺评定报告(?:\(PQR\))?",),
    "pwps": (r"预焊接工艺规程(?:\(pWPS\))?",),
    "wps": (r"焊接工艺规程(?:\(WPS\))?", r"焊接工艺卡"),
    "welding_record": (r"焊接工艺评定焊接及检验记录", r"焊接记录"),
    "rt_report": (r"射线检测报告(?:书|\(主页\)|\(附页\))?",),
    "ut_report": (r"超声(?:波)?检测报告(?:书|\(主页\)|\(附页\))?",),
}


def annotate_document_pages(result):
    pages = {}
    for fragment in result.get("fragments") or []:
        if not isinstance(fragment, dict):
            continue
        page = fragment.get("pageNo")
        if isinstance(page, bool) or not isinstance(page, int) or page <= 0:
            continue
        entries = pages.setdefault(page, [])
        text = fragment.get("text")
        confidence = fragment.get("confidence")
        if (not isinstance(text, str) or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float)) or not .75 <= confidence <= 1):
            continue
        title = re.sub(r"\s+", "", text).replace("（", "(").replace("）", ")")
        matches = [kind for kind, patterns in TITLES.items() if any(re.fullmatch(pattern, title, re.IGNORECASE) for pattern in patterns)]
        for kind in matches:
            entries.append({"documentKind": kind, "source": deepcopy(fragment)})
    classifications = []
    for page, entries in sorted(pages.items()):
        kinds = sorted({entry["documentKind"] for entry in entries})
        classifications.append({"pageNo": page, "status": "identified" if len(kinds) == 1 else "ambiguous" if kinds else "unknown",
                                "documentKind": kinds[0] if len(kinds) == 1 else None, "titleEvidence": entries})
    result["documentPageClassification"] = {"version": "explicit-page-titles-v1", "scope": "observed_fragment_pages_only",
        "complete": False, "pages": classifications}
