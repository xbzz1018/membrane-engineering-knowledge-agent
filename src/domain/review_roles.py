"""Agent responsibilities are distinct from document types and issue domains."""

from src.domain.review_rules import evidence_role, validate_evidence

REVIEW_ROLES = ("retrieval", "material", "review")
ROLE_LABELS = {"retrieval": "资料检索", "material": "材料核验", "review": "综合审查"}
AGENT_NAMES = {"retrieval": "RetrievalAgent", "material": "MaterialAgent", "review": "ReviewAgent"}


def validate_review_evidence(evidence, workers):
    from src.domain.material_mass import mass_issues

    # Prices remain an optional business check. An ordinary design/specification
    # package must not fail simply because no procurement price was submitted.
    checks = set()
    if "material" in workers:
        checks.add("material")
    if "review" in workers:
        checks.update(("design", "material"))
        if any(evidence_role(row) == "price" for row in evidence):
            checks.add("price")
    if not checks:
        return []
    return [*validate_evidence(evidence, checks), *mass_issues(evidence, checks)]
