"""Transparent developer-written synthetic retrieval fixture, never internal data."""

import hashlib
import json
from pathlib import Path


def build():
    documents, queries = [], []
    models = ["PTFE-502", "ETFE-250", "PVC-900"]
    for model in models:
        for role, text in [
            ("design", "设计要求：核验拉伸强度与节点承载，安装预张力按节点详图控制。"),
            ("material", "材料规格：名义厚度0.8 mm，拉伸强度6000 N/5cm，防火等级B1。"),
            ("price", "历史价格：华东地区含税人民币每平方米280元；不作为正式报价。"),
        ]:
            for revision, start, end, version in [
                ("R1", "2025-01-01", "2025-12-31", 1),
                ("R2", "2026-01-01", "2026-12-31", 2),
                ("R3", "2027-01-01", None, 3),
            ]:
                key = f"{model}-{role}-{revision}"
                documents.append({"key": key, "filename": key + ".txt", "upload_version": version,
                    "content": f"SYNTHETIC developer fixture。型号 {model}，适用版次 {revision}。{text}",
                    "metadata": {"engineering_model": model, "applicable_revision": revision,
                                 "document_type": role, "effective_from": start, "effective_to": end}})
        for kind in ("near-model", "unknown-date", "private", "other-project"):
            other_model = model + "0" if kind == "near-model" else model
            key = model + "-" + kind
            documents.append({"key": key, "filename": key + ".txt", "upload_version": 2,
                "classification": "internal" if kind == "private" else "public",
                "scope": "other" if kind == "other-project" else "target",
                "content": f"SYNTHETIC 材料规格：型号 {other_model}，厚度0.8 mm，强度6000 N/5cm。",
                "metadata": {"engineering_model": other_model, "applicable_revision": "R2", "document_type": "material",
                             "effective_from": None if kind == "unknown-date" else "2026-01-01", "effective_to": None}})
        def query(name, text, category, filters, relevant):
            queries.append({"eval_id": model + "-" + name, "query": text, "category": category,
                            "filters": filters, "relevant_document_keys": relevant})
        current = {"engineering_model": model, "applicable_revision": "R2", "effective_on": "2026-11-02"}
        query("spec", "名义厚度", "exact_model", {**current, "document_type": "material"}, [model + "-material-R2"])
        query("multi", "拉伸强度", "multi_relevant", current, [model + "-design-R2", model + "-material-R2"])
        query("history", "材料规格", "effective_date", {"engineering_model": model, "document_type": "material", "effective_on": "2025-12-31"}, [model + "-material-R1"])
        query("future", "材料规格", "effective_date", {"engineering_model": model, "applicable_revision": "R3", "document_type": "material", "effective_on": "2027-01-01"}, [model + "-material-R3"])
        # Near/unknown/private/cross-project records are deliberate exclusion traps.
        # The near model never qualifies; future query pins R3.
        query("version", "节点", "upload_version", {**current, "upload_version": 2, "document_type": "design"}, [model + "-design-R2"])
        query("paraphrase", "这个产品在施工时如何施加初始张力", "semantic_paraphrase", current, [model + "-design-R2"])
        query("empty-query", "", "exact_only", {**current, "document_type": "price"}, [model + "-price-R2"])
        query("absent-revision", "厚度", "unanswerable_filter", {**current, "applicable_revision": "R99"}, [])
        query("absent-topic", "供应商法定代表人的护照号码", "unanswerable_semantic", current, [])
    for index in range(80):
        key = f"DISTRACTOR-{index:03}"
        documents.append({"key": key, "filename": key + ".txt", "upload_version": 1,
            "content": f"SYNTHETIC 工程归档{index}：消防检修、施工节点、名义厚度与材料拉伸强度通用检查，未提供目标型号依据。",
            "metadata": {"engineering_model": f"OTHER-{index}", "applicable_revision": "R1", "document_type": "other",
                         "effective_from": "2026-01-01", "effective_to": None}})
    queries.extend([
        {"eval_id": "unfiltered-design", "query": "PTFE-502 R2 安装预张力", "category": "unfiltered",
         "filters": {}, "relevant_document_keys": ["PTFE-502-design-R2"]},
        {"eval_id": "unfiltered-spec", "query": "ETFE-250 R2 防火等级", "category": "unfiltered",
         "filters": {}, "relevant_document_keys": ["ETFE-250-material-R2"]},
        {"eval_id": "missing-model", "query": "材料规格", "category": "unanswerable_filter",
         "filters": {"engineering_model": "NO-SUCH-MODEL"}, "relevant_document_keys": []},
    ])
    return {"schema_version": 1, "dataset_kind": "synthetic_development_fixture",
            "label_author": "developer", "not_a_held_out_test": True,
            "limitations": ["Template-generated distractors and repeated model families", "No domain expert labels",
                            "Semantic no-answer has no calibrated score threshold; empty-return rate is not QA accuracy"],
            "documents": documents, "queries": queries}


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "data/eval/retrieval_business_v1.json"
    if path.exists():
        raise SystemExit("Frozen file already exists; create a new version instead of overwriting labels")
    raw = (json.dumps(build(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    path.with_suffix(".sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii")
    print(path)
