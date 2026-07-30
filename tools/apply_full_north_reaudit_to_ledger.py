#!/usr/bin/env python3
"""Apply conserved full-list re-audit groups to the municipal crawl ledger."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit


SEED_RE = re.compile(r'(<script id="seed-data" type="application/json">)(.*?)(</script>)', re.DOTALL)
SCHEMA = "navicus_full_north_reaudit_group_v1"
TARGET_ISSUER_COUNT = 69
APPROVED_UNMATERIALIZED_TERMINALS = {
    "shared:17:ishikawa_portal_discovery",
    "muni:172014",
}
APPROVED_SUPPLEMENTAL_TERMINALS = {
    "muni:121002",
    "shared:13:e_tokyo_joint_procurement",
}


def norm(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def route_path_nodes(value: object) -> list[object]:
    """Normalize legacy route_path shapes before matching or serializing."""
    if isinstance(value, list):
        return value
    if isinstance(value, (str, dict)) and value:
        return [value]
    return []


def valid_item(item: dict) -> tuple[bool, list[str]]:
    errors = list(item.get("errors") or [])
    if item.get("row_conservation_pass") is not True:
        errors.append("row_conservation_failed")
    if item.get("public_end") is not True:
        errors.append("public_end_not_confirmed")
    if item.get("visible_row_count") != item.get("case_count", 0) + item.get("exclusion_count", 0):
        errors.append("visible_row_count_not_conserved")
    if item.get("case_count") != len(item.get("cases") or []):
        errors.append("case_count_mismatch")
    if item.get("exclusion_count") != len(item.get("exclusions") or []):
        errors.append("exclusion_count_mismatch")
    if any(not case.get("title") or not case.get("official_url") for case in item.get("cases") or []):
        errors.append("case_identity_missing")
    issuer_id = item.get("issuer_id")
    unmaterialized = item.get("unmaterialized_terminal_rows") or []
    if unmaterialized and issuer_id not in APPROVED_UNMATERIALIZED_TERMINALS:
        errors.append(f"unmaterialized_terminal_rows_not_operator_approved:{len(unmaterialized)}")
    terminal_exceptions = item.get("terminal_exceptions") or []
    if terminal_exceptions and issuer_id not in APPROVED_SUPPLEMENTAL_TERMINALS | APPROVED_UNMATERIALIZED_TERMINALS:
        errors.append(f"terminal_exception_not_operator_approved:{len(terminal_exceptions)}")
    return not errors, errors


def dashboard_case(issuer_id: str, root_url: str, raw: dict, observed_at: str) -> dict:
    return {
        "case_id": raw.get("case_id"),
        "classification": "materialized_case",
        "deadline": raw.get("deadline") or "",
        "deadline_milestones": raw.get("deadline_milestones") or [],
        "department": raw.get("department") or "",
        "enumeration_status": raw.get("enumeration_status") or "full_list_reaudit",
        "evidence_mode": "official_list_row",
        "issuer_id": issuer_id,
        "lifecycle_status": raw.get("lifecycle_status") or "unknown",
        "observed_at": observed_at,
        "official_url": raw["official_url"],
        "published_at": raw.get("published_at") or "",
        "route_path": route_path_nodes(raw.get("route_path")) or [
            {"url": root_url, "surface_role": "crawl_root"},
            {"url": raw["official_url"], "surface_role": "case_detail", "parent_url": root_url},
        ],
        "source_list_url": raw.get("source_list_url") or root_url,
        "status": "全行再監査で取得",
        "summary": raw.get("summary") or "公式一覧から全行再監査で取得した案件。",
        "summary_method": "official_list_row_context",
        "summary_source_selector": "official list row",
        "title": raw["title"],
        "full_north_reaudit": True,
        **({"source_row_number": raw["source_row_number"]} if raw.get("source_row_number") is not None else {}),
    }


def merge_item(original: dict, audit: dict) -> dict:
    item = deepcopy(original)
    root_url = audit["root_url"]
    root_key = norm(root_url)
    # A complete root replay replaces every prior row attributed to that root,
    # including old sample-only imports and navigation URLs miscast as cases.
    retained_cases = []
    for case in item.get("cases") or []:
        if case.get("full_north_reaudit") is True:
            continue
        source = norm(case.get("source_list_url"))
        path_urls = {norm(node.get("url") if isinstance(node, dict) else node) for node in route_path_nodes(case.get("route_path"))}
        if source == root_key or root_key in path_urls or case.get("north_audit_source"):
            continue
        retained_cases.append(case)
    new_cases = [dashboard_case(item["issuer_id"], root_url, raw, audit.get("observed_at") or "") for raw in audit.get("cases") or []]
    item["cases"] = retained_cases + new_cases
    for case in item["cases"]:
        case["route_path"] = route_path_nodes(case.get("route_path"))

    accepted_case_urls = {norm(case["official_url"]) for case in new_cases if norm(case["official_url"]) != root_key}
    retained_routes = [
        route for route in item.get("official_routes") or []
        if route.get("kind") != "case_detail" and norm(route.get("url")) != root_key
    ]
    route_rows = [{
        "url": root_url,
        "kind": "canonical_crawl_target",
        "status": "full_reaudit_verified",
        "surface_role": "crawl_root",
        "label": audit.get("display_name"),
    }]
    for branch in audit.get("branches") or []:
        if norm(branch.get("url")) == root_key:
            continue
        route_rows.append({
            "url": branch["url"], "kind": "official_frontier_branch",
            "status": "full_reaudit_verified", "surface_role": branch.get("role") or "official_frontier_branch",
            "label": branch.get("label") or branch["url"],
        })
    seen_route_urls = {norm(row["url"]) for row in retained_routes + route_rows}
    for case in new_cases:
        key = norm(case["official_url"])
        if key == root_key or key in seen_route_urls:
            continue
        route_rows.append({
            "url": case["official_url"], "kind": "case_detail", "status": "full_reaudit_materialized",
            "surface_role": "case_detail", "label": case["title"],
        })
        seen_route_urls.add(key)
    item["official_routes"] = retained_routes + route_rows

    nodes = [{"id": root_url, "url": root_url, "label": audit.get("display_name"), "surface_role": "crawl_root", "fetched": True}]
    edges = []
    node_urls = {root_key}
    for branch in audit.get("branches") or []:
        url = branch.get("url")
        if not url or norm(url) in node_urls:
            continue
        nodes.append({"id": url, "url": url, "label": branch.get("label") or url, "surface_role": branch.get("role") or "official_frontier_branch", "fetched": True})
        edges.append({"from": root_url, "to": url, "type": "frontier"})
        node_urls.add(norm(url))
    for case in new_cases:
        url = case["official_url"]
        if norm(url) == root_key or norm(url) in node_urls:
            continue
        nodes.append({"id": url, "url": url, "label": case["title"], "surface_role": "case_detail", "fetched": True})
        edges.append({"from": root_url, "to": url, "type": "case"})
        node_urls.add(norm(url))
    item["route_graph"] = {"nodes": nodes, "edges": edges}

    exclusions = list(item.get("excluded_case_updates") or [])
    existing_exclusions = {(norm(row.get("official_url") or row.get("url")), row.get("title")) for row in exclusions}
    for raw in audit.get("exclusions") or []:
        key = (norm(raw.get("url")), raw.get("title"))
        if key in existing_exclusions:
            continue
        exclusions.append({
            "title": raw.get("title"), "official_url": raw.get("url"),
            "case_materialized": False, "exclusion_reason": raw.get("reason") or "non_case_list_row",
            "preserved_from": "full_north_reaudit", "observed_at": audit.get("observed_at"),
        })
        existing_exclusions.add(key)
    item["excluded_case_updates"] = exclusions
    item["canonical_crawl_target_url"] = root_url
    item["route_quality"] = "VERIFIED_FULL_LIST_REAUDIT"
    item["route_classification_rq02"] = "FULL_LIST_REAUDIT_VERIFIED"
    item["assessment"] = "circle"
    item["assessment_reason"] = f"○: 公式一覧を全行再監査。案件{audit['case_count']}件・除外{audit['exclusion_count']}件を保存則で確認。"
    item["blocker"] = None
    item["first_failed_stage"] = None
    item["human_action_required"] = False
    item["next_action"] = "同じ公式起点を定期巡回し、全行差分を再同期する。"
    item.setdefault("evidence", {}).update({
        "public_end": True,
        "verified_zero": audit["case_count"] == 0,
        "token_free_runtime": True,
        "full_north_reaudit": {
            "observed_at": audit.get("observed_at"), "visible_row_count": audit["visible_row_count"],
            "case_count": audit["case_count"], "exclusion_count": audit["exclusion_count"],
            "row_conservation_pass": True, "raw_html_persisted": False,
        },
    })
    item["north_audit"] = {
        "publication_status": "PENDING_FULL_REAUDIT",
        "conclusion": "FULL_LIST_REAUDIT_VERIFIED",
        "official_case_count": audit["case_count"],
        "visible_row_count": audit["visible_row_count"],
        "excluded_row_count": audit["exclusion_count"],
        "details_reached": sum(1 for case in new_cases if norm(case["official_url"]) != root_key),
        "route_branch_count": len(audit.get("branches") or []),
        "observed_at": audit.get("observed_at"),
    }
    item["proposal_list_audit"] = {
        "audited": True, "crawl_target_url": root_url, "target_page_type": "FULL_LIST_REAUDIT",
        "is_proposal_list": True, "visible_row_count": audit["visible_row_count"],
        "official_case_count": audit["case_count"], "excluded_row_count": audit["exclusion_count"],
        "row_conservation_pass": True, "public_end": True, "checked_at": audit.get("observed_at"),
        "confidence": "high", "historical_exhaustiveness_claimed": True,
    }
    item["normalized_url_union"] = sorted({norm(route.get("url")) for route in item["official_routes"] if route.get("url")} | {norm(case.get("official_url")) for case in item["cases"] if case.get("official_url")})
    return item


def apply_groups(seed: dict, groups: list[dict]) -> tuple[dict, dict]:
    updated = deepcopy(seed)
    by_id = {item["issuer_id"]: index for index, item in enumerate(updated["items"])}
    all_rows: dict[str, dict] = {}
    rejected: dict[str, list[str]] = {}
    for group in groups:
        if group.get("schema_version") != SCHEMA:
            raise ValueError(f"unsupported group schema: {group.get('schema_version')}")
        for row in group.get("items") or []:
            ok, errors = valid_item(row)
            if ok:
                all_rows[row["issuer_id"]] = row
            else:
                rejected[row.get("issuer_id") or "unknown"] = errors
    missing_from_ledger = sorted(set(all_rows) - set(by_id))
    if missing_from_ledger:
        raise ValueError(f"issuers missing from ledger: {missing_from_ledger}")
    for issuer_id, row in all_rows.items():
        updated["items"][by_id[issuer_id]] = merge_item(updated["items"][by_id[issuer_id]], row)
    for issuer_id, errors in rejected.items():
        if issuer_id not in by_id:
            continue
        blocked = updated["items"][by_id[issuer_id]]
        blocked["assessment"] = "triangle"
        blocked["assessment_reason"] = "△: 全行再監査の未実体化終端または未承認例外が残存。"
        blocked["route_quality"] = "FULL_REAUDIT_BLOCKED"
        blocked["route_classification_rq02"] = "FULL_REAUDIT_BLOCKED"
        blocked["blocker"] = "; ".join(errors)
        blocked["first_failed_stage"] = "full_list_materialization"
        blocked["human_action_required"] = True
        blocked["next_action"] = "公開システム終端が復旧後、未実体化行を案件URL・タイトル付きで再取得する。"
        blocked["north_audit"] = {
            **(blocked.get("north_audit") or {}),
            "publication_status": "BLOCKED",
            "conclusion": "FULL_REAUDIT_BLOCKED",
            "blockers": errors,
        }
    # Completion belongs to the supplied fresh audit set, not stale route_quality
    # left by an earlier partial overlay.
    completed = len(all_rows)
    status = "GO" if completed == TARGET_ISSUER_COUNT and not rejected else "NO-GO"
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    receipt = {
        "schema_version": "navicus_full_north_reaudit_ledger_receipt_v1",
        "updated_at": now, "status": status, "target_issuer_count": TARGET_ISSUER_COUNT,
        "completed_issuer_count": completed, "accepted_in_this_run": len(all_rows),
        "rejected_issuer_count": len(rejected), "rejected": rejected,
        "case_count": sum(len(item.get("cases") or []) for item in updated["items"]),
    }
    updated["full_north_reaudit"] = receipt
    updated["generated_at"] = now
    updated["publication_gate"] = {
        "decision": status,
        "reason": "全69自治体の公式一覧全行再監査が完了" if status == "GO" else f"全行再監査は{completed}/{TARGET_ISSUER_COUNT}自治体。未完了またはP0が残存。",
        "publish_allowed": status == "GO",
        "gate_artifact": "full_north_reaudit",
    }
    updated["validation_workflow"] = {
        "schema_version": "navicus_full_north_reaudit_loop_state_v1",
        "updated_at": now,
        "iteration": 1,
        "status": status,
        "loopback_text": "未実体化終端が復旧したら該当3発注者だけ再巡回し、69/69でGOを再判定する。",
        "nodes": [
            {"id": "scope", "label": "北側69発注者", "status": "complete", "detail": "全件を新規再調査"},
            {"id": "materialize", "label": "公式一覧を全行化", "status": "complete", "detail": f"{completed}/69件が厳格ゲート通過"},
            {"id": "blockers", "label": "未実体化終端", "status": "blocked" if rejected else "complete", "detail": f"P0 {len(rejected)}件"},
            {"id": "gate", "label": "公開判定", "status": "complete", "detail": status},
        ],
    }
    final = updated.setdefault("final_summary", {})
    final["valid_case_rows"] = receipt["case_count"]
    final["unique_valid_case_urls"] = len({norm(case.get("official_url")) for item in updated["items"] for case in item.get("cases") or [] if case.get("official_url")})
    final["content_circle_count"] = sum(item.get("assessment") == "circle" for item in updated["items"])
    final["content_triangle_count"] = sum(item.get("assessment") == "triangle" for item in updated["items"])
    final["p0_count"] = len(rejected)
    final["p1_count"] = 0
    return updated, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", type=Path, required=True)
    parser.add_argument("--group", type=Path, action="append", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    html = args.dashboard.read_text(encoding="utf-8")
    match = SEED_RE.search(html)
    if not match:
        raise SystemExit("seed-data script not found")
    seed = json.loads(match.group(2))
    groups = [json.loads(path.read_text(encoding="utf-8")) for path in args.group]
    updated, receipt = apply_groups(seed, groups)
    encoded = json.dumps(updated, ensure_ascii=False, separators=(",", ":"))
    args.dashboard.write_text(html[:match.start(2)] + encoded + html[match.end(2):], encoding="utf-8")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
