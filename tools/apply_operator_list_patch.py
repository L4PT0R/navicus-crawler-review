#!/usr/bin/env python3
"""Apply conserved operator-approved list rows to the crawl ledger."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re


SEED_RE = re.compile(r'(<script id="seed-data" type="application/json">)(.*?)(</script>)', re.DOTALL)
SCHEMA = "navicus_operator_list_patch_v1"


def apply(seed: dict, patch: dict) -> dict:
    if patch.get("schema_version") != SCHEMA:
        raise ValueError("unsupported patch schema")
    updated = deepcopy(seed)
    by_id = {item["issuer_id"]: item for item in updated["items"]}
    for row in patch.get("items") or []:
        if not row.get("row_conservation_pass") or not row.get("public_end"):
            raise ValueError(f"unconserved list: {row.get('issuer_id')}")
        if row.get("visible_row_count") != row.get("case_count") + row.get("exclusion_count"):
            raise ValueError(f"count mismatch: {row.get('issuer_id')}")
        item = by_id[row["issuer_id"]]
        root = row["root_url"]
        cases = []
        for raw in row.get("cases") or []:
            cases.append({
                **raw,
                "case_state": "CASE_DISCOVERED",
                "status": "全行取得済み",
                "full_list_operator_patch": True,
            })
        exclusions = [{
            "title": raw["title"], "official_url": raw["url"],
            "published_at": raw.get("context", ""), "case_materialized": False,
            "exclusion_reason": raw["reason"], "preserved_from": "operator_list_patch",
            "observed_at": row["observed_at"],
            "route_path": [root, raw["url"]],
        } for raw in row.get("exclusions") or []]
        item["cases"] = cases
        item["excluded_case_updates"] = exclusions
        item["canonical_crawl_target_url"] = root
        item["official_routes"] = [
            {"url": root, "kind": "canonical_proposal_list", "status": "operator_confirmed_full_list", "surface_role": "crawl_root", "label": f"{row['display_name']} 公式一覧"},
            *[{"url": case["official_url"], "kind": "case_detail", "status": "full_list_materialized", "surface_role": "case_detail", "label": case["title"]} for case in cases],
            *[{"url": exclusion["official_url"], "kind": "excluded_list_row", "status": exclusion["exclusion_reason"], "surface_role": "excluded_list_row", "label": exclusion["title"]} for exclusion in exclusions],
        ]
        nodes = [{"id": root, "url": root, "label": f"{row['display_name']} 公式一覧", "surface_role": "crawl_root", "fetched": True}]
        edges = []
        for detail in cases + exclusions:
            url = detail["official_url"]
            nodes.append({"id": url, "url": url, "label": detail["title"], "surface_role": "case_detail" if detail in cases else "excluded_list_row", "fetched": True})
            edges.append({"from": root, "to": url, "type": "case" if detail in cases else "excluded_row"})
        item["route_graph"] = {"nodes": nodes, "edges": edges}
        item["assessment"] = "circle"
        item["assessment_reason"] = f"○: 指定公式一覧の可視{row['visible_row_count']}行を全件保存（案件{row['case_count']}・除外{row['exclusion_count']}）。"
        item["route_quality"] = "VERIFIED_OPERATOR_FULL_LIST"
        item["human_action_required"] = False
        item["proposal_list_audit"] = {
            "audited": True, "canonical_crawl_target_url": root, "target_page_type": "OPERATOR_CONFIRMED_FULL_LIST",
            "visible_row_count": row["visible_row_count"], "official_case_count": row["case_count"],
            "excluded_row_count": row["exclusion_count"], "row_conservation_pass": True, "public_end": True,
            "checked_at": row["observed_at"],
        }
    updated["operator_list_patch"] = {
        "schema_version": SCHEMA,
        "observed_at": patch.get("observed_at"),
        "issuer_ids": [row["issuer_id"] for row in patch.get("items") or []],
        "status": "APPLIED",
    }
    updated["generated_at"] = patch.get("observed_at") or updated.get("generated_at")
    summary = updated.setdefault("final_summary", {})
    summary["valid_case_rows"] = sum(len(item.get("cases") or []) for item in updated["items"])
    summary["unique_valid_case_urls"] = len({case.get("official_url") for item in updated["items"] for case in item.get("cases") or [] if case.get("official_url")})
    summary["content_circle_count"] = sum(item.get("assessment") == "circle" for item in updated["items"])
    summary["content_triangle_count"] = sum(item.get("assessment") == "triangle" for item in updated["items"])
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    args = parser.parse_args()
    html = args.dashboard.read_text(encoding="utf-8")
    match = SEED_RE.search(html)
    if not match:
        raise SystemExit("seed-data script not found")
    updated = apply(json.loads(match.group(2)), json.loads(args.patch.read_text(encoding="utf-8")))
    encoded = json.dumps(updated, ensure_ascii=False, separators=(",", ":"))
    args.dashboard.write_text(html[:match.start(2)] + encoded + html[match.end(2):], encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
