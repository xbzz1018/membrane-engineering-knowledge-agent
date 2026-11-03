"""Strict developer-labeled issue matching; does not claim semantic entailment."""


def match_issues(issues: list[dict], gold: list[dict], document_ids: list[str]) -> dict:
    remaining = list(range(len(gold)))
    matches, extras = [], []
    for issue in issues:
        if not (issue.get("requires_human") or issue.get("severity") == "conflict"):
            continue
        documents = {eid.split(":", 1)[0] for eid in issue.get("evidence_ids", [])}
        hit = next((index for index in remaining if (
            issue.get("issue_type") == gold[index]["issue_type"]
            and (not gold[index].get("domain") or issue.get("domain") == gold[index]["domain"])
            and documents == {document_ids[i] for i in gold[index]["evidence_documents"]}
        )), None)
        if hit is None:
            extras.append(issue)
        else:
            matches.append({"gold_index": hit, "issue_id": issue.get("issue_id", "")})
            remaining.remove(hit)
    return {
        "tp": len(matches), "fp": len(extras), "fn": len(remaining),
        "matched": matches, "unexpected_blocking_findings": extras, "unmatched_gold_indexes": remaining,
        "strict_issue_pass": not extras and not remaining,
    }
