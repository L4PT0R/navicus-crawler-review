#!/usr/bin/env python3
"""Build the read-only Mie-north count audit payload for GitHub Pages."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parents[1]
RUN = WORKSPACE / "work/mie_north_case_count_reaudit_2026-07-30/run_01"
OUT = REPO / "north-audit-data.json"
MITO_RESULT = WORKSPACE / "work/mito_citywide_recruitment_2026-07-30/result.json"
LIST_REPAIR_ROOT = WORKSPACE / "work/municipal_proposal_list_repair_2026-07-30"
SAPPORO_RESULT = WORKSPACE / "work/sapporo_current_procurement_2026-07-30/result.json"
OPERATOR_ROUTE_OVERRIDES = WORKSPACE / "data/north_operator_route_overrides_v1.json"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def walk_records(value: object):
    if isinstance(value, dict):
        if value.get("issuer_id") and value.get("conclusion"):
            yield value
        for child in value.values():
            yield from walk_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_records(child)


def result_records() -> dict[str, dict]:
    best: dict[str, tuple[int, dict]] = {}
    for path in sorted((RUN / "children").glob("**/*")):
        if path.suffix not in {".json", ".jsonl"} or not path.is_file():
            continue
        try:
            if path.suffix == ".jsonl":
                values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                values = [json.loads(path.read_text(encoding="utf-8"))]
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for value in values:
            for row in walk_records(value):
                score = (
                    20 * bool(row.get("route_graph"))
                    + 10 * bool(row.get("pagination_evidence"))
                    + 5 * len(row.get("discovery_rounds") or [])
                    + min(30, len(row.get("checked_urls") or []))
                )
                issuer_id = str(row["issuer_id"])
                if issuer_id not in best or score > best[issuer_id][0]:
                    best[issuer_id] = (score, row)
    return {issuer_id: row for issuer_id, (_, row) in best.items()}


def normalize_url(value: object) -> dict[str, str] | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return {"url": value, "label": value}
    if isinstance(value, dict):
        url = str(value.get("url") or value.get("official_url") or "")
        if url.startswith(("http://", "https://")):
            return {
                "url": url,
                "label": str(value.get("label") or value.get("title") or value.get("role") or url),
            }
    return None


def route_payload(record: dict, fallback_root: str, checked: list[dict[str, str]]) -> dict:
    graph = record.get("route_graph") or {}
    root_value = graph.get("root") if isinstance(graph, dict) else None
    root = normalize_url(root_value) or normalize_url(fallback_root) or (checked[0] if checked else None)
    branches: list[dict] = []
    if isinstance(graph, dict):
        pending_branches = list(graph.get("branches") or [])
        while pending_branches:
            branch = pending_branches.pop(0)
            if isinstance(branch, str):
                branches.append({"label": branch, "url": "", "role": "branch", "case_count": 0})
                continue
            if not isinstance(branch, dict):
                continue
            pending_branches.extend(child for child in (branch.get("children") or []) if isinstance(child, (dict, str)))
            url_item = normalize_url(branch)
            details = branch.get("case_details")
            detail_urls = []
            if isinstance(details, list):
                detail_urls = [item for item in (normalize_url(v) for v in details) if item]
            branches.append({
                "label": str(branch.get("label") or branch.get("role") or (url_item or {}).get("label") or "公式一覧"),
                "url": (url_item or {}).get("url", ""),
                "role": str(branch.get("role") or "branch"),
                "case_count": as_int(branch.get("rows") or branch.get("case_count") or (len(detail_urls) if detail_urls else 0)),
                "details": detail_urls,
            })
    if not branches and root:
        branch_sources = checked[1:6] or [root]
        for index, source in enumerate(branch_sources):
            branches.append({
                "label": source.get("label") or ("公式一覧・公開面" if index == 0 else "確認した枝"),
                "url": source["url"],
                "role": "proposal_or_procurement_list" if index == 0 else "checked_official_branch",
                "case_count": as_int(record.get("official_list_case_count")) if index == 0 else 0,
                "details": [],
            })
    return {"root": root, "branches": branches}


def current_pages_case_urls(issuer_id: str) -> set[str]:
    html_text = (REPO / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="seed-data" type="application/json">(.*?)</script>', html_text, re.S)
    if not match:
        return set()
    seed = json.loads(match.group(1))
    item = next((row for row in seed.get("items", []) if row.get("issuer_id") == issuer_id), {})
    return {str(case.get("official_url") or "") for case in item.get("cases", []) if case.get("official_url")}


def apply_mito_live_overlay(items: list[dict]) -> None:
    if not MITO_RESULT.exists():
        return
    result = json.loads(MITO_RESULT.read_text(encoding="utf-8"))
    if result.get("issuer_id") != "muni:082015" or not result.get("row_conservation_pass"):
        return
    target = next((item for item in items if item["issuer_id"] == "muni:082015"), None)
    if target is None:
        return
    cases = result.get("cases") or []
    grouped: dict[str, list[dict]] = {}
    for case in cases:
        grouped.setdefault(case.get("source_page_url") or result["crawl_root_url"], []).append(case)
    def page_number(url: str) -> int:
        match = re.search(r"list5-(\d+)\.html", url)
        return int(match.group(1)) if match else 999
    branches = []
    for page_url in sorted(result.get("visited_pages", []), key=page_number):
        page_cases = grouped.get(page_url, [])
        number = page_number(page_url)
        branches.append({
            "label": f"募集カテゴリ {number}ページ目" if number != 999 else "募集カテゴリ",
            "url": page_url,
            "role": "pagination",
            "case_count": len(page_cases),
            "scanned": True,
            "details": [
                {"label": case.get("title") or case.get("official_url"), "url": case.get("official_url")}
                for case in page_cases
            ],
        })
    existing_urls = current_pages_case_urls("muni:082015")
    target.update({
        "official_rows": result.get("confirmed_case_count", 0),
        "details_reached": result.get("confirmed_case_count", 0),
        "delta": result.get("confirmed_case_count", 0) - target["pages_count"],
        "conclusion": "UNDERCOUNT_SUSPECTED",
        "confidence": "high",
        "root_url": result["crawl_root_url"],
        "route": {
            "root": {"url": result["crawl_root_url"], "label": "水戸市 全庁『募集』カテゴリ"},
            "branches": branches,
        },
        "checked_urls": [
            {"url": url, "label": f"募集カテゴリ {page_number(url)}ページ目"}
            for url in result.get("visited_pages", [])
        ] + [
            {"url": case["official_url"], "label": case["title"]}
            for case in cases
        ],
        "missing_candidates": [
            {"title": case["title"], "url": case["official_url"], "status": "公式詳細確認済み・Pages未収載候補"}
            for case in cases if case.get("official_url") not in existing_urls
        ],
        "duplicate_groups": [],
        "discovery_rounds": [
            {"round": 1, "result": "ユーザー指定の全庁『募集』カテゴリを起点として採用"},
            {"round": 2, "result": "公開ページ1〜7を全踏破し209行を保存則で分類"},
            {"round": 3, "result": "候補10件すべての同一公式ホスト詳細でプロポーザル方式を確認"},
        ],
        "pagination_evidence": [{
            "visited_page_count": result.get("visited_page_count"),
            "pagination_terminal": result.get("pagination_terminal"),
            "visible_unique_row_count": result.get("visible_unique_row_count"),
            "row_conservation_pass": result.get("row_conservation_pass"),
        }],
        "observed_at": result.get("observed_at", ""),
    })


def apply_full_list_repair_overlays(items: list[dict]) -> None:
    """Replace frozen/current-only counts with conserved official-list results."""
    if not LIST_REPAIR_ROOT.exists():
        return
    for result_path in sorted(LIST_REPAIR_ROOT.glob("*.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("schema_version") != "navicus_municipal_proposal_list_v1":
            continue
        if not result.get("row_conservation_pass") or result.get("raw_html_persisted"):
            continue
        target = next((item for item in items if item["issuer_id"] == result.get("issuer_id")), None)
        if target is None:
            continue
        cases = result.get("cases") or []
        existing_urls = current_pages_case_urls(target["issuer_id"])
        reached = as_int(result.get("detail_reached_count"))
        confirmed = as_int(result.get("detail_proposal_confirmed_count"))
        total = as_int(result.get("proposal_list_case_count"))
        conclusion = "OFFICIAL_LIST_ENUMERATED"
        # Dedicated official-list membership is sufficient for the audit count;
        # body keyword confirmation is a separate content-quality signal because
        # official sub-sites may use a different main-content container.
        if result.get("detail_check_enabled") and reached < total:
            conclusion = "DETAIL_REVIEW_REQUIRED"
        target.update({
            "official_rows": total,
            "details_reached": reached,
            "delta": total - target["pages_count"],
            "conclusion": conclusion,
            "confidence": "high" if result.get("detail_check_enabled") and reached == total else "medium",
            "root_url": result["crawl_root_url"],
            "route": {
                "root": {"url": result["official_entry_url"], "label": f"{result['display_name']}公式サイト"},
                "branches": [{
                    "label": result.get("root_scope") or "全庁公式一覧",
                    "url": result["crawl_root_url"],
                    "role": "whole_site_proposal_category",
                    "case_count": total,
                    "scanned": True,
                    "details": [
                        {"label": case.get("title") or case.get("official_url"), "url": case.get("official_url")}
                        for case in cases
                    ],
                }],
            },
            "checked_urls": [
                {"url": result["crawl_root_url"], "label": result.get("root_scope") or "全庁公式一覧"},
            ] + [
                {"url": case["official_url"], "label": case["title"]} for case in cases
            ],
            "missing_candidates": [
                {"title": case["title"], "url": case["official_url"], "status": "公式一覧掲載・Pages未収載"}
                for case in cases if case.get("official_url") not in existing_urls
            ],
            "duplicate_groups": [],
            "discovery_rounds": [
                {"round": 1, "result": "既知案件ではなく、自治体公式一覧そのものを母集団として固定"},
                {"round": 2, "result": f"表示{result.get('visible_unique_row_count', 0)}行を、プロポーザル{total}件・対象外{result.get('non_proposal_row_count', 0)}行へ保存的に分類"},
                {"round": 3, "result": f"案件詳細へ{reached}/{total}件到達し、方式確認{confirmed}/{total}件"},
            ],
            "pagination_evidence": [{
                "visible_unique_row_count": result.get("visible_unique_row_count"),
                "proposal_list_case_count": total,
                "non_proposal_row_count": result.get("non_proposal_row_count"),
                "row_conservation_pass": True,
                "frozen_case_seed_used": False,
            }],
            "observed_at": result.get("observed_at", ""),
        })


def apply_sapporo_attachment_overlay(items: list[dict]) -> None:
    if not SAPPORO_RESULT.exists():
        return
    result = json.loads(SAPPORO_RESULT.read_text(encoding="utf-8"))
    if (
        result.get("schema_version") != "navicus_sapporo_current_procurement_v1"
        or not result.get("row_conservation_pass")
        or result.get("document_raw_saved")
    ):
        return
    target = next((item for item in items if item["issuer_id"] == "muni:011002"), None)
    if target is None:
        return
    city_root, policy_root = result["current_root_urls"]
    city_cases = [case for case in result.get("cases", []) if case.get("source_list_url") == city_root]
    policy_cases = [case for case in result.get("cases", []) if case.get("source_list_url") == policy_root]
    proposal_count = as_int(result.get("citywide_proposal_occurrence_count"))
    selected_document = result.get("selected_document_url") or ""
    individual_city_cases = [case for case in city_cases if case.get("official_url") and case.get("official_url") != selected_document]
    attempts = result.get("attachment_attempts") or []
    attachment_details = [
        {"label": f"{attempt.get('kind', '').upper()} {attempt.get('status', '')}", "url": attempt.get("url", "")}
        for attempt in attempts if attempt.get("url")
    ]
    archive_branches = [
        {
            "label": "政策企画部・年度別結果（現行件数から除外）",
            "url": archive,
            "role": "result_archive",
            "case_count": 0,
            "scanned": True,
            "details": [],
        }
        for archive in result.get("result_archive_urls") or []
    ]
    target.update({
        "official_rows": proposal_count,
        "details_reached": len({case.get("official_url") for case in individual_city_cases if case.get("official_url")}),
        "delta": proposal_count - target["pages_count"],
        "conclusion": "ROOT_INCOMPLETE",
        "confidence": "high",
        "root_url": city_root,
        "route": {
            "root": {"url": "https://www.city.sapporo.jp/", "label": "札幌市公式サイト"},
            "branches": [
                {
                    "label": f"市長部局全体・現在公募 → {result.get('selected_document_kind', '').upper()}本文{result.get('citywide_document_row_count', 0)}行",
                    "url": city_root,
                    "role": "whole_site_current_procurement_attachment_list",
                    "case_count": proposal_count,
                    "scanned": True,
                    "details": [
                        {"label": case.get("title") or case.get("official_url"), "url": case.get("official_url")}
                        for case in city_cases
                    ],
                },
                {
                    "label": "政策企画部・現在案件（部局限定）",
                    "url": policy_root,
                    "role": "department_proposal_list",
                    "case_count": as_int(result.get("policy_proposal_occurrence_count")),
                    "scanned": True,
                    "details": [
                        {"label": case.get("title") or case.get("official_url"), "url": case.get("official_url")}
                        for case in policy_cases
                    ],
                },
            ] + archive_branches,
        },
        "checked_urls": [
            {"url": city_root, "label": "市長部局全体・公募中案件一覧"},
            {"url": policy_root, "label": "政策企画部・現在案件"},
        ] + attachment_details + [
            {"url": url, "label": "政策企画部・年度別結果（除外）"}
            for url in result.get("result_archive_urls") or []
        ] + [
            {"url": case["official_url"], "label": case["title"]} for case in policy_cases
        ],
        "missing_candidates": [
            {
                "title": case.get("title") or "添付文書内案件",
                "url": selected_document,
                "status": "PDF/Excel本文から抽出・個別案件URLの確定が必要",
            }
            for case in city_cases if case.get("official_url") == selected_document
        ],
        "duplicate_groups": [],
        "discovery_rounds": [
            {"round": 1, "result": "ipankyousou.htmlを政策企画部の現在案件枝として固定し、R7/R6結果URLを現行探索から除外"},
            {"round": 2, "result": f"市長部局全体のippan-koubo添付を{result.get('selected_document_kind', '').upper()}から本文抽出"},
            {"round": 3, "result": f"添付{result.get('citywide_document_row_count', 0)}行から公募型企画競争{proposal_count}件を分類。個別詳細URLの完全到達は継続課題"},
        ],
        "pagination_evidence": [{
            "selected_document_url": selected_document,
            "selected_document_kind": result.get("selected_document_kind"),
            "document_sha256": result.get("document_sha256"),
            "citywide_document_row_count": result.get("citywide_document_row_count"),
            "citywide_proposal_occurrence_count": proposal_count,
            "citywide_non_proposal_count": result.get("citywide_non_proposal_count"),
            "row_conservation_pass": True,
            "result_archives_excluded": result.get("result_archives_seen_and_excluded"),
        }],
        "observed_at": result.get("observed_at", ""),
    })


def _looks_like_case_detail(url: str, root_url: str, excluded: set[str]) -> bool:
    if not url or url == root_url or url in excluded:
        return False
    path = re.sub(r"/+", "/", url.split("?", 1)[0].split("#", 1)[0])
    if path.endswith(("/", "/index.html", "/index.php")):
        return False
    if re.search(r"/index_\d+\.html$", path):
        return False
    return bool(re.search(r"(?:/\d{4,}|/d\d+|\.html|\.htm|\.php)$", path))


def apply_operator_route_overrides(items: list[dict]) -> None:
    """Promote operator-confirmed list pages and demote result-only routes."""
    if not OPERATOR_ROUTE_OVERRIDES.exists():
        return
    payload = json.loads(OPERATOR_ROUTE_OVERRIDES.read_text(encoding="utf-8"))
    for override in payload.get("items") or []:
        target = next((item for item in items if item["issuer_id"] == override.get("issuer_id")), None)
        if target is None:
            continue
        root_url = override["root_url"]
        excluded = set(override.get("excluded_result_urls") or [])
        dropped = set(override.get("drop_urls") or [])
        if override.get("observed_official_rows") is not None:
            observed_rows = as_int(override["observed_official_rows"])
            target["official_rows"] = observed_rows
            target["details_reached"] = min(as_int(target.get("details_reached")), observed_rows)
            target["delta"] = observed_rows - as_int(target.get("pages_count"))
        checked = target.get("checked_urls") or []
        existing_primary_details = []
        for existing_branch in target.get("route", {}).get("branches") or []:
            if existing_branch.get("url") == root_url:
                existing_primary_details.extend(existing_branch.get("details") or [])
        inferred_details = [
            {"url": row["url"], "label": row.get("label") or row["url"]}
            for row in checked
            if _looks_like_case_detail(row.get("url", ""), root_url, excluded)
        ]
        deduped_details = []
        seen_detail_urls = set()
        primary_detail_candidates = existing_primary_details or inferred_details
        for detail in primary_detail_candidates:
            if detail["url"] not in seen_detail_urls:
                seen_detail_urls.add(detail["url"])
                deduped_details.append(detail)
        primary_branch = {
            "label": override["root_label"],
            "url": root_url,
            "role": override["root_role"],
            "case_count": target.get("official_rows", 0),
            "scanned": bool(target.get("official_rows", 0)),
            "details": deduped_details,
        }
        branches = [primary_branch]
        for branch in override.get("additional_current_roots") or []:
            branches.append({
                "label": branch["label"],
                "url": branch["url"],
                "role": branch["role"],
                "case_count": 0,
                "scanned": False,
                "details": [],
            })
        if not override.get("only_current_root"):
            for branch in target.get("route", {}).get("branches") or []:
                url = branch.get("url", "")
                if not url or url == root_url or url in excluded or url in dropped:
                    continue
                if any(url == existing.get("url") for existing in branches):
                    continue
                branches.append(branch)
        for result_url in sorted(excluded):
            branches.append({
                "label": "結果ページ（現行探索・件数から除外）",
                "url": result_url,
                "role": "result_archive_excluded",
                "case_count": 0,
                "scanned": True,
                "details": [],
            })
        ordered_checked = [
            {"url": root_url, "label": override["root_label"]},
        ] + [
            {"url": branch["url"], "label": branch["label"]}
            for branch in override.get("additional_current_roots") or []
        ] + [
            {"url": url, "label": "結果ページ（除外）"} for url in sorted(excluded)
        ] + [row for row in checked if row.get("url") not in dropped]
        unique_checked = []
        seen_checked = set()
        for row in ordered_checked:
            if row["url"] and row["url"] not in seen_checked:
                seen_checked.add(row["url"])
                unique_checked.append(row)
        previous_rounds = target.get("discovery_rounds") or []
        target.update({
            "root_url": root_url,
            "route": {
                "root": {"url": root_url, "label": override["root_label"]},
                "branches": branches,
            },
            "checked_urls": unique_checked,
            "discovery_rounds": [{
                "round": 1,
                "result": "オペレーター確認済みの専用一覧をクロール起点へ昇格。自治体・県トップからの探索を廃止",
            }] + [
                {**round_row, "round": index + 2}
                for index, round_row in enumerate(previous_rounds[:2])
            ],
            "operator_root_override": True,
            "operator_root_basis": override.get("operator_basis", ""),
            "excluded_result_urls": sorted(excluded),
        })


def main() -> None:
    scope = {row["issuer_id"]: row for row in load_csv(RUN / "target_scope.csv")}
    summaries: list[dict[str, str]] = []
    for lane in ("A", "B", "C"):
        summaries.extend(load_csv(RUN / f"parents/{lane}/summary.csv"))
    details = result_records()
    items = []
    for summary in summaries:
        issuer_id = summary["issuer_id"]
        meta = scope.get(issuer_id, {})
        record = details.get(issuer_id, {})
        checked = []
        for value in record.get("checked_urls") or []:
            item = normalize_url(value)
            if item and item["url"] not in {x["url"] for x in checked}:
                checked.append(item)
        missing = []
        for value in record.get("missing_case_candidates") or []:
            if not isinstance(value, dict):
                continue
            url_item = normalize_url(value)
            missing.append({
                "title": str(value.get("title") or value.get("note") or value.get("candidate_type") or "未収載候補"),
                "url": (url_item or {}).get("url", ""),
                "status": str(value.get("status") or value.get("reason") or "要確認"),
            })
        items.append({
            "issuer_id": issuer_id,
            "prefecture_code": meta.get("prefecture_code", ""),
            "prefecture": meta.get("prefecture", ""),
            "display_name": meta.get("display_name", issuer_id),
            "lane": summary.get("child_id") or summary.get("lane") or "C",
            "conclusion": summary.get("conclusion", "PUBLIC_BOUNDARY_UNMEASURABLE"),
            "pages_count": as_int(summary.get("pages_display_case_count")),
            "canonical_count": as_int(summary.get("canonical_ledger_logical_case_count")),
            "official_rows": as_int(summary.get("official_list_case_count")),
            "details_reached": as_int(summary.get("official_detail_reached_count")),
            "delta": as_int(summary.get("delta")),
            "confidence": summary.get("confidence", "unknown"),
            "root_url": meta.get("canonical_crawl_target_url", ""),
            "route": route_payload(record, meta.get("canonical_crawl_target_url", ""), checked),
            "checked_urls": checked,
            "missing_candidates": missing,
            "duplicate_groups": (record.get("duplicate_groups") or [])[:12],
            "discovery_rounds": (record.get("discovery_rounds") or [])[:3],
            "pagination_evidence": (record.get("pagination_evidence") or [])[:20],
            "observed_at": record.get("observed_at", ""),
        })
    items.sort(key=lambda row: (row["prefecture_code"], row["display_name"]))
    apply_mito_live_overlay(items)
    apply_full_list_repair_overlays(items)
    apply_sapporo_attachment_overlay(items)
    apply_operator_route_overrides(items)
    counts = Counter(item["conclusion"] for item in items)
    payload = {
        "schema_version": "navicus_mie_north_audit_pages_v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_manifest_sha256": (RUN / "input_manifest.sha256").read_text(encoding="utf-8").strip(),
        "publication_status": "REVIEW_ONLY_NO_GO",
        "scope": "都道府県コード01北海道〜23愛知・Pages掲載69発注者",
        "summary": {
            "issuer_count": len(items),
            "pages_count": sum(item["pages_count"] for item in items),
            "official_row_observation_count": sum(item["official_rows"] for item in items),
            "conclusion_counts": dict(counts),
        },
        "items": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
