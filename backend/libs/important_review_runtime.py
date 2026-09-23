"""Freeze the maintained skill before dispatch; browser input cannot supply rule text."""
from libs.important_node_review import skill_for_node


def attach_important_review(run, body):
    if not body.get("importantNodeReview"):
        return
    skill = skill_for_node(run.get("nodeId"))
    if not skill or not run.get("inputDocumentVersionIds"):
        raise ValueError("重要节点审查需要受支持的节点和明确的资料版本。")
    run["importantReviewSnapshot"] = skill
    run["promptVersion"] = f"important-node-review@{skill['version']}"


def important_review_prompt(run):
    snapshot = run.get("importantReviewSnapshot")
    if not snapshot:
        return {}
    return {"importantNodeReview": snapshot,
            "importantNodeReviewPolicy": "逐条对照本节点审查要求；未覆盖或缺证据的条目明确列出，不能用已有原子项通过冒充全节点通过。数值与标准版本以原文核实为准；全部为辅助意见。"}
