#!/usr/bin/env python3
"""Merge accepted north-audit routes and verified cases into the municipal ledger."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit


SEED_RE = re.compile(
    r'(<script id="seed-data" type="application/json">)(.*?)(</script>)',
    re.DOTALL,
)
ZERO_CONCLUSIONS = {"EXACT_CONFIRMED"}
TERMINAL_CONCLUSIONS = {"EXTERNAL_SYSTEM_TERMINAL_CONFIRMED"}


def norm(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def label_is_url(value: str | None) -> bool:
    return bool(value and value.strip().lower().startswith(("http://", "https://")))


def merge_routes(existing: list[dict], additions: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    order: list[str] = []
    for route in existing + additions:
        key = norm(route.get("url"))
        if not key:
            continue
        if key not in merged:
            order.append(key)
            merged[key] = deepcopy(route)
        elif route in additions:
            merged[key] = {**merged[key], **deepcopy(route)}
    return [merged[key] for key in order]


def branch_path(root_url: str, branch: dict, detail_url: str | None = None) -> list[dict]:
    branch_url = branch.get("url") or root_url
    path = [{"url": root_url, "surface_role": "crawl_root"}]
    if norm(branch_url) != norm(root_url):
        path.append({
            "url": branch_url,
            "surface_role": branch.get("role") or "official_frontier_branch",
            "parent_url": root_url,
        })
    if detail_url and norm(detail_url) not in {norm(row["url"]) for row in path}:
        path.append({
            "url": detail_url,
            "surface_role": "case_detail",
            "parent_url": branch_url,
        })
    return path


def dashboard_case(
    issuer_id: str,
    title: str,
    url: str,
    branch: dict,
    root_url: str,
    observed_at: str,
    source: str,
    extra: dict | None = None,
) -> dict:
    extra = extra or {}
    deadline = (
        extra.get("deadline")
        or extra.get("participation_deadline")
        or extra.get("proposal_deadline")
        or extra.get("entry_deadline")
        or ""
    )
    return {
        "case_id": None,
        "classification": "materialized_case",
        "deadline": deadline,
        "deadline_milestones": [],
        "enumeration_status": "materialized_case",
        "evidence_mode": "official_list_or_detail_html",
        "issuer_id": issuer_id,
        "lifecycle_status": "unknown",
        "observed_at": observed_at,
        "official_url": url,
        "published_at": "",
        "route_path": branch_path(root_url, branch, url),
        "source_list_url": branch.get("url") or root_url,
        "status": "監査台帳へ同期済み",
        "summary": f"北側経路監査で、公式の{branch.get('label') or '一覧・探索面'}から到達を確認した案件。",
        "summary_method": "official_route_audit_context",
        "summary_source_selector": "official list/detail link",
        "title": title,
        "north_audit_source": source,
        **({"operator_case_metadata": extra} if extra else {}),
    }


def merge_item(item: dict, audit: dict, final: dict | None) -> tuple[dict, int, int]:
    updated = deepcopy(item)
    root_url = audit.get("root_url") or audit.get("route", {}).get("root", {}).get("url")
    if not root_url:
        raise ValueError(f"missing accepted root: {audit.get('issuer_id')}")
    branches = deepcopy((audit.get("route") or {}).get("branches") or [])
    if final and final.get("branches"):
        # The final human-approved branch inventory has priority over derived audit branches.
        final_by_url = {norm(row.get("url")): row for row in final["branches"] if row.get("url")}
        for branch in branches:
            override = final_by_url.pop(norm(branch.get("url")), None)
            if override:
                branch.update(override)
        branches.extend(final_by_url.values())
    if not branches:
        branches = [{
            "url": root_url,
            "label": (audit.get("route") or {}).get("root", {}).get("label") or audit["display_name"],
            "role": "accepted_crawl_root",
            "case_count": audit.get("official_rows", 0),
            "details": [],
        }]

    excluded = {norm(url) for url in audit.get("excluded_result_urls") or []}
    route_additions = [{
        "url": root_url,
        "kind": "canonical_crawl_target",
        "status": "operator_accepted",
        "surface_role": "crawl_root",
        "label": (audit.get("route") or {}).get("root", {}).get("label") or audit["display_name"],
    }]
    for branch in branches:
        if not branch.get("url"):
            continue
        route_additions.append({
            "url": branch["url"],
            "kind": "official_frontier_branch",
            "status": "operator_accepted",
            "surface_role": branch.get("role") or "official_frontier_branch",
            "label": branch.get("label") or branch.get("role") or branch["url"],
        })

    before_case_count = len(updated.get("cases") or [])
    cases = list(updated.get("cases") or [])
    existing_urls = {norm(case.get("official_url")) for case in cases if case.get("official_url")}
    existing_pairs = {(norm(case.get("official_url")), case.get("title") or "") for case in cases}
    operator_by_url: dict[str, list[dict]] = {}
    for row in (final or {}).get("eligible_current_open_cases") or []:
        if row.get("url"):
            operator_by_url.setdefault(norm(row["url"]), []).append(row)

    # Add operator-verified current cases first so generic URL labels cannot mask them.
    for rows in operator_by_url.values():
        for row in rows:
            url = row["url"]
            pair = (norm(url), row.get("title") or url)
            if pair in existing_pairs or (norm(url) in existing_urls and len(rows) == 1):
                continue
            branch = next((b for b in branches if norm(b.get("url")) == norm(root_url)), branches[0])
            cases.append(dashboard_case(
                audit["issuer_id"], row.get("title") or url, url, branch, root_url,
                audit.get("observed_at") or "", "north_no_go_final_repairs_v1", row,
            ))
            existing_pairs.add(pair)
            existing_urls.add(norm(url))

    zero_now = audit.get("conclusion") in ZERO_CONCLUSIONS and audit.get("official_rows") == 0
    if not zero_now:
        for branch in branches:
            role = str(branch.get("role") or "")
            if "result" in role:
                continue
            for detail in branch.get("details") or []:
                if isinstance(detail, str):
                    detail = {"url": detail, "label": detail}
                url = detail.get("url")
                key = norm(url)
                if not url or key in excluded or key in existing_urls or key in operator_by_url:
                    continue
                title = detail.get("label") or url
                cases.append(dashboard_case(
                    audit["issuer_id"], title, url, branch, root_url,
                    audit.get("observed_at") or "", "north-audit-data.json",
                ))
                existing_urls.add(key)
                existing_pairs.add((key, title))
                route_additions.append({
                    "url": url,
                    "kind": "case_detail",
                    "status": "downstream_evidence",
                    "surface_role": "case_detail",
                    "label": None if label_is_url(title) else title,
                })

    nodes: list[dict] = [{
        "id": root_url,
        "url": root_url,
        "label": (audit.get("route") or {}).get("root", {}).get("label") or audit["display_name"],
        "surface_role": "crawl_root",
        "fetched": True,
    }]
    edges: list[dict] = []
    node_urls = {norm(root_url)}
    for branch in branches:
        branch_url = branch.get("url")
        if not branch_url:
            continue
        if norm(branch_url) not in node_urls:
            nodes.append({
                "id": branch_url, "url": branch_url,
                "label": branch.get("label") or branch.get("role") or branch_url,
                "surface_role": branch.get("role") or "official_frontier_branch",
                "fetched": bool(branch.get("scanned")),
            })
            node_urls.add(norm(branch_url))
            edges.append({"from": root_url, "to": branch_url, "type": "frontier"})
        for detail in branch.get("details") or []:
            url = detail if isinstance(detail, str) else detail.get("url")
            label = url if isinstance(detail, str) else detail.get("label") or url
            if not url or norm(url) in excluded or zero_now:
                continue
            if norm(url) not in node_urls:
                nodes.append({"id": url, "url": url, "label": label, "surface_role": "case_detail", "fetched": True})
                node_urls.add(norm(url))
            if norm(url) != norm(branch_url):
                edges.append({"from": branch_url, "to": url, "type": "case"})

    updated["official_routes"] = merge_routes(updated.get("official_routes") or [], route_additions)
    updated["cases"] = cases
    updated["canonical_crawl_target_url"] = root_url
    updated["route_graph"] = {"nodes": nodes, "edges": edges}
    updated["route_quality"] = (
        "ACCEPTED_EXTERNAL_SYSTEM_TERMINAL"
        if audit.get("conclusion") in TERMINAL_CONCLUSIONS
        else "VERIFIED_NORTH_AUDIT_ROUTE"
    )
    updated["route_classification_rq02"] = audit.get("conclusion")
    updated["assessment"] = "circle"
    updated["assessment_reason"] = (
        f"○: 北側再監査で{audit.get('conclusion')}。採用起点・枝・公式案件を自治体別台帳へ同期。"
    )
    updated["blocker"] = None
    updated["first_failed_stage"] = None
    updated["human_action_required"] = False
    updated["next_action"] = "採用済み起点を定期巡回し、新規案件を差分同期する。"
    evidence = updated.setdefault("evidence", {})
    evidence["public_end"] = True
    evidence["verified_zero"] = zero_now
    evidence["token_free_runtime"] = True
    evidence["north_audit_sync"] = {
        "observed_at": audit.get("observed_at"),
        "conclusion": audit.get("conclusion"),
        "confidence": audit.get("confidence"),
        "official_case_count": audit.get("official_rows", 0),
        "details_reached": audit.get("details_reached", 0),
        "route_branch_count": len(branches),
        "source": "north-audit-data.json",
    }
    updated["north_audit"] = {
        "publication_status": "GO",
        "conclusion": audit.get("conclusion"),
        "official_case_count": audit.get("official_rows", 0),
        "details_reached": audit.get("details_reached", 0),
        "route_branch_count": len(branches),
        "observed_at": audit.get("observed_at"),
    }
    updated["proposal_list_audit"] = {
        "audited": True,
        "crawl_target_url": root_url,
        "target_page_type": audit.get("conclusion"),
        "is_proposal_list": audit.get("conclusion") not in TERMINAL_CONCLUSIONS,
        "official_case_count": audit.get("official_rows", 0),
        "details_reached": audit.get("details_reached", 0),
        "checked_at": audit.get("observed_at"),
        "confidence": audit.get("confidence"),
        "historical_exhaustiveness_claimed": audit.get("conclusion") == "OFFICIAL_LIST_ENUMERATED",
    }
    updated["normalized_url_union"] = sorted({
        norm(route.get("url")) for route in updated["official_routes"] if route.get("url")
    } | {
        norm(case.get("official_url")) for case in cases if case.get("official_url")
    })
    return updated, before_case_count, len(cases)


def sync(seed: dict, audit_data: dict, final_data: dict | None = None) -> tuple[dict, dict]:
    if audit_data.get("publication_status") != "GO":
        raise ValueError("north audit publication_status must be GO")
    updated = deepcopy(seed)
    indexes = {row.get("issuer_id"): index for index, row in enumerate(updated.get("items") or [])}
    final_by_id = {row["issuer_id"]: row for row in (final_data or {}).get("items") or []}
    missing = [row["issuer_id"] for row in audit_data.get("items") or [] if row["issuer_id"] not in indexes]
    if missing:
        raise ValueError(f"north audit issuers missing from ledger: {missing}")
    before_total = sum(len(row.get("cases") or []) for row in updated["items"])
    prior_receipt = seed.get("north_audit_sync") or {}
    initial_before_total = (
        prior_receipt.get("before_case_count", before_total)
        if prior_receipt.get("schema_version") == "navicus_north_audit_ledger_sync_receipt_v1"
        else before_total
    )
    changed: list[str] = []
    added = 0
    for audit in audit_data.get("items") or []:
        index = indexes[audit["issuer_id"]]
        merged, before_count, after_count = merge_item(updated["items"][index], audit, final_by_id.get(audit["issuer_id"]))
        updated["items"][index] = merged
        changed.append(audit["issuer_id"])
        added += after_count - before_count
    synced_at = datetime.now().astimezone().isoformat(timespec="seconds")
    receipt = {
        "schema_version": "navicus_north_audit_ledger_sync_receipt_v1",
        "synced_at": synced_at,
        "source_publication_status": audit_data["publication_status"],
        "issuer_count": len(changed),
        "changed_issuer_ids": changed,
        "dashboard_item_count": len(updated["items"]),
        "before_case_count": initial_before_total,
        "after_case_count": sum(len(row.get("cases") or []) for row in updated["items"]),
        "case_count_added": sum(len(row.get("cases") or []) for row in updated["items"]) - initial_before_total,
        "accepted_count": audit_data.get("summary", {}).get("accepted_count"),
        "blocking_count": audit_data.get("summary", {}).get("blocking_count"),
    }
    updated["generated_at"] = synced_at
    updated["north_audit_sync"] = receipt
    final_summary = updated.setdefault("final_summary", {})
    final_summary["valid_case_rows"] = receipt["after_case_count"]
    final_summary["unique_valid_case_urls"] = len({
        norm(case.get("official_url"))
        for item in updated["items"]
        for case in item.get("cases") or []
        if case.get("official_url")
    })
    final_summary["route_review_required_count"] = sum(
        item.get("route_quality") in {"REVIEW_REQUIRED", "UNVERIFIED"}
        for item in updated["items"]
    )
    final_summary["active_route_p2_count"] = final_summary["route_review_required_count"]
    return updated, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", type=Path, required=True)
    parser.add_argument("--north-audit", type=Path, required=True)
    parser.add_argument("--final-repairs", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    html = args.dashboard.read_text(encoding="utf-8")
    match = SEED_RE.search(html)
    if not match:
        raise SystemExit("seed-data script not found")
    seed = json.loads(match.group(2))
    audit = json.loads(args.north_audit.read_text(encoding="utf-8"))
    final = json.loads(args.final_repairs.read_text(encoding="utf-8")) if args.final_repairs else None
    updated, receipt = sync(seed, audit, final)
    encoded = json.dumps(updated, ensure_ascii=False, separators=(",", ":"))
    args.dashboard.write_text(html[:match.start(2)] + encoded + html[match.end(2):], encoding="utf-8")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
