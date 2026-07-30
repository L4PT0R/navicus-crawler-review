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
        for branch in graph.get("branches") or []:
            if isinstance(branch, str):
                branches.append({"label": branch, "url": "", "role": "branch", "case_count": 0})
                continue
            if not isinstance(branch, dict):
                continue
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
                "details": detail_urls[:12],
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
    return {"root": root, "branches": branches[:20]}


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
            "root_url": meta.get("root_url", ""),
            "route": route_payload(record, meta.get("root_url", ""), checked),
            "checked_urls": checked[:30],
            "missing_candidates": missing[:30],
            "duplicate_groups": (record.get("duplicate_groups") or [])[:12],
            "discovery_rounds": (record.get("discovery_rounds") or [])[:3],
            "pagination_evidence": (record.get("pagination_evidence") or [])[:20],
            "observed_at": record.get("observed_at", ""),
        })
    items.sort(key=lambda row: (row["prefecture_code"], row["display_name"]))
    apply_mito_live_overlay(items)
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
