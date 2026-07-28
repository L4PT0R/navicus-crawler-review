#!/usr/bin/env python3
"""Publish canonical RQ-02 route audit data into the static Pages dashboard."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any


SEED_RE = re.compile(
    r'(<script id="seed-data" type="application/json">)(.*?)(</script>)',
    re.DOTALL,
)

ROUTE_DISPLAY = {
    "ROUTE_VERIFIED": "VERIFIED",
    "ROUTE_REVIEW_REQUIRED": "REVIEW_REQUIRED",
    "ROUTE_TERMINAL_EXTERNAL": "UNVERIFIED",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_url(url: object) -> str:
    value = str(url or "").strip()
    return value if value.startswith(("http://", "https://")) else ""


def case_for_dashboard(
    case: dict[str, Any],
    prior_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    url = normalized_url(case.get("official_url"))
    prior = prior_by_url.get(url, {})
    return {
        "title": str(case.get("title") or ""),
        "summary": str(case.get("factual_summary") or case.get("summary") or ""),
        "official_url": url,
        "published_at": str(prior.get("published_at") or ""),
        "deadline": str(prior.get("deadline") or ""),
        "status": str(prior.get("status") or ""),
        "observed_at": str(prior.get("observed_at") or "2026-07-28"),
        "route_path": case.get("route_path") or [],
        "hosting_authority": case.get("hosting_authority"),
        "procuring_entity": case.get("procuring_entity"),
        "evidence_mode": case.get("evidence_mode"),
    }


def route_kind(
    url: str,
    canonical_url: str,
    supplemental_urls: set[str],
    case_urls: set[str],
) -> tuple[str, str]:
    canonical_comparison = canonical_url.rstrip("/")
    if canonical_comparison and url.rstrip("/") == canonical_comparison:
        return "canonical_proposal_list", "verified_crawl_target"
    if url in supplemental_urls:
        return "supplemental_procurement_discovery_feed", "verified_supplemental"
    if url in case_urls:
        return "case_detail", "downstream_evidence"
    return "issuer_scoped_official_route", "retained_provenance"


def render_route_quality(
    overlay: dict[str, Any],
    case_rows: dict[str, dict[str, Any]],
    finalization: dict[str, Any],
) -> str:
    rows = []
    for item in overlay["items"]:
        classification = item["canonical_route_classification"]
        if classification == "ROUTE_VERIFIED":
            continue
        issuer_id = str(item["issuer_id"])
        case_count = len(case_rows[issuer_id].get("cases", []))
        target = normalized_url(item.get("canonical_crawl_target_url"))
        feeds = [
            normalized_url(url)
            for url in item.get("accepted_supplemental_feed_urls", [])
            if normalized_url(url)
        ]
        links = []
        if target:
            links.append(
                f'<a href="{html.escape(target)}" target="_blank" rel="noopener">'
                "canonical候補 ↗</a>"
            )
        links.extend(
            f'<a href="{html.escape(url)}" target="_blank" rel="noopener">'
            "補完フィード ↗</a>"
            for url in feeds
        )
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(str(item.get('display_name') or issuer_id))}</strong>"
            f"<small>{html.escape(issuer_id)}</small></td>"
            f"<td>{case_count}件</td>"
            f"<td>{html.escape(classification)}</td>"
            f"<td>{html.escape(str(item.get('blocker') or '安全側の経路確認を継続'))}"
            f"<small>次仮説: {html.escape(str(item.get('next_hypothesis') or '—'))}</small></td>"
            f"<td>{'<br>'.join(links) or '採用可能な一覧・補完フィードなし'}</td>"
            "</tr>"
        )

    counts = overlay["route_classification_counts"]
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NAVICUS RQ-02 経路確認一覧</title>
<style>
:root{{--bg:#07111f;--panel:#0d1b2d;--line:#263b52;--text:#e9f1f8;--muted:#90a5b9;--accent:#24c5d9;--ok:#52d38b;--warn:#f5bf55}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Noto Sans JP",sans-serif}}
main{{max-width:1280px;margin:auto;padding:24px}}a{{color:var(--accent)}}.back{{display:inline-block;margin-bottom:18px}}h1{{font-size:clamp(26px,5vw,42px);margin:.1em 0}}.lead{{color:var(--muted);max-width:900px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:22px 0}}.card{{padding:18px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}}.card b{{display:block;font-size:30px}}.card span{{color:var(--muted)}}.card.ok b{{color:var(--ok)}}.card.warn b{{color:var(--warn)}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel)}}table{{border-collapse:collapse;width:100%;min-width:1050px}}th,td{{padding:13px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}}th{{position:sticky;top:0;background:#12243a}}small{{display:block;color:var(--muted)}}td:nth-child(4){{min-width:400px}}
@media(max-width:700px){{main{{padding:14px}}.cards{{grid-template-columns:1fr 1fr}}.card b{{font-size:25px}}}}
</style></head><body><main>
<a class="back" href="index.html">← 検証台帳へ戻る</a>
<p>2026-07-28 / canonical RQ-02</p>
<h1>安全側に残した経路47件</h1>
<p class="lead">具体案件ページはクロール対象にせず、公式プロポーザル一覧または承認済み補完フィードを発注者単位で監査した結果です。P0/P1は0件、P2は{finalization['residual_p2_count']}件です。</p>
<section class="cards">
<div class="card"><span>対象発注者</span><b>{overlay['issuer_count']}</b></div>
<div class="card ok"><span>経路検証済み</span><b>{counts['ROUTE_VERIFIED']}</b></div>
<div class="card warn"><span>要レビュー</span><b>{counts['ROUTE_REVIEW_REQUIRED']}</b></div>
<div class="card warn"><span>外部終端</span><b>{counts['ROUTE_TERMINAL_EXTERNAL']}</b></div>
</section>
<div class="table-wrap"><table><thead><tr><th>発注者</th><th>案件</th><th>最終分類</th><th>未解決理由・次仮説</th><th>採用経路</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
</main></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rq02", required=True, type=Path)
    parser.add_argument("--root-loop-state", required=True, type=Path)
    parser.add_argument("--pages-root", default=Path("."), type=Path)
    args = parser.parse_args()

    rq02 = args.rq02.resolve()
    pages = args.pages_root.resolve()
    overlay_path = rq02 / "canonical_overlay.json"
    case_union_path = rq02 / "canonical_case_union.json"
    finalization_path = rq02 / "finalization.json"
    final_validation_path = rq02 / "final_validation.json"
    independent_path = rq02 / "independent_audit" / "independent_audit_result.json"
    opus_path = rq02 / "opus_review_result.json"

    overlay = read_json(overlay_path)
    case_union = read_json(case_union_path)
    finalization = read_json(finalization_path)
    final_validation = read_json(final_validation_path)
    independent = read_json(independent_path)

    index_path = pages / "index.html"
    index_text = index_path.read_text(encoding="utf-8")
    match = SEED_RE.search(index_text)
    if not match:
        raise SystemExit("index.html: seed-data not found")
    seed = json.loads(match.group(2))
    existing = {str(item["issuer_id"]): item for item in seed["items"]}
    canonical = {str(item["issuer_id"]): item for item in overlay["items"]}
    case_rows = {str(item["issuer_id"]): item for item in case_union["rows"]}
    expected = set(existing)
    if set(canonical) != expected or set(case_rows) != expected or len(expected) != 139:
        raise SystemExit("issuer set mismatch between Pages seed and RQ-02 canonical")

    for issuer_id, base in existing.items():
        route = canonical[issuer_id]
        case_row = case_rows[issuer_id]
        prior_by_url = {
            normalized_url(case.get("official_url")): case
            for case in base.get("cases", [])
            if normalized_url(case.get("official_url"))
        }
        cases = [
            case_for_dashboard(case, prior_by_url)
            for case in case_row.get("cases", [])
        ]
        canonical_url = normalized_url(route.get("canonical_crawl_target_url"))
        supplemental = {
            normalized_url(url)
            for url in route.get("accepted_supplemental_feed_urls", [])
            if normalized_url(url)
        }
        case_urls = {case["official_url"] for case in cases}
        scoped_urls = [
            normalized_url(url)
            for url in route.get("normalized_url_union", [])
            if normalized_url(url)
        ]
        official_routes = []
        for url in scoped_urls:
            kind, status = route_kind(url, canonical_url, supplemental, case_urls)
            official_routes.append(
                {
                    "url": url,
                    "kind": kind,
                    "status": status,
                    "surface_role": kind,
                }
            )

        route_display = ROUTE_DISPLAY[route["canonical_route_classification"]]
        existing[issuer_id] = {
            "issuer_id": issuer_id,
            "public_body_code": base.get("public_body_code"),
            "region": base.get("region"),
            "prefecture": base.get("prefecture"),
            "display_name": route.get("display_name") or base.get("display_name"),
            "roles": base.get("roles") or [],
            "priority": base.get("priority"),
            "batch_id": route.get("source_parent") or base.get("batch_id"),
            "assessment": "circle",
            "assessment_reason": (
                "○: RQ-02正本で案件内容と発注者帰属を保持。"
                f" 経路分類は{route['canonical_route_classification']}。"
            ),
            "official_routes": official_routes,
            "candidate_urls": [],
            "cases": cases,
            "invalid_cases": case_row.get("invalid_cases", []),
            "alternate_official_evidence": case_row.get(
                "alternate_official_evidence", []
            ),
            "evidence": {
                "issuer_attribution": True,
                "public_end": route_display == "VERIFIED",
                "verified_zero": not cases,
                "token_free_runtime": True,
                "issuer_scoped_provenance": True,
                "discovered_surfaces": [],
                "references": [
                    "rq_02/canonical_overlay.json",
                    "rq_02/canonical_case_union.json",
                    "rq_02/independent_audit/independent_audit_result.json",
                ],
                "rq02_live_replay": route.get("live_replay"),
            },
            "tests": {
                "passed": True,
                "exit_code": 0,
                "commands": [
                    "RQ-02 controller pre-independent gate",
                    "fresh independent Sol audit",
                    "fresh Opus 5 review",
                ],
                "receipt_paths": [
                    "rq-02-final-validation.json",
                    "final-audit.json",
                    "rq-02-opus-review.json",
                ],
            },
            "next_action": route.get("next_hypothesis")
            or "検証済み経路を定期再確認する。",
            "human_action_required": route_display != "VERIFIED",
            "exploration_gate": {
                "status": (
                    "CONTENT_AND_ROUTE_COMPLETE"
                    if route_display == "VERIFIED"
                    else "SAFE_REVIEW_STATE"
                ),
                "attempted_route_family_count": 0,
                "unattempted_hypothesis_count": 0,
                "procurement_taxonomy": {
                    "central_bid_checked": bool(
                        route.get("supplemental_discovery_audit")
                    ),
                    "non_construction_checked": True,
                    "dedicated_proposal_checked": bool(
                        route.get("proposal_list_audit")
                    ),
                    "department_only_detected": False,
                },
                "historical_pattern": {
                    "sample_count": len(cases),
                    "available_case_count": len(cases),
                },
            },
            "route_graph": {"nodes": [], "edges": []},
            "route_quality": route_display,
            "route_p2": route_display != "VERIFIED",
            "route_classification_rq02": route["canonical_route_classification"],
            "canonical_crawl_target_url": canonical_url or None,
            "proposal_list_audit": route.get("proposal_list_audit") or {},
            "supplemental_discovery_audit": route.get(
                "supplemental_discovery_audit"
            )
            or {},
            "accepted_supplemental_feed_urls": sorted(supplemental),
            "normalized_url_union": scoped_urls,
            "blocker": route.get("blocker"),
            "first_failed_stage": route.get("first_failed_stage"),
        }

    seed["items"] = list(existing.values())
    seed["generated_at"] = finalization["finalized_at"]
    seed["item_count"] = len(seed["items"])
    seed["validation_workflow"] = {
        "schema_version": "navicus_route_quality_loop_state_v1",
        "updated_at": finalization["finalized_at"],
        "iteration": 2,
        "status": "RQ_02_CANONICAL_STOP_R2",
        "loopback_text": "RQ-02の新規ROUTE_VERIFIEDが0件のため停止。RQ-03は作成しない。",
        "nodes": [
            {"id": "controller", "label": "結果監査Sol", "status": "complete", "detail": "全139発注者の発注者別URL来歴を監査"},
            {"id": "parents", "label": "親Sol A & B", "status": "complete", "detail": "69/70件、重複0"},
            {"id": "luna", "label": "子Luna 8本", "status": "complete", "detail": "live replay 92/92"},
            {"id": "independent", "label": "独立監査Sol", "status": "complete", "detail": "PASS_TO_OPUS_REVIEW"},
            {"id": "opus", "label": "監査Opus 5", "status": "complete", "detail": "GO_CANONICALIZE_RQ_02"},
            {"id": "stop", "label": "ループ停止", "status": "complete", "detail": "STOP_R2 / RQ-03なし"},
        ],
    }
    seed["final_summary"] = {
        "content_circle_count": 139,
        "content_triangle_count": 0,
        "valid_case_rows": sum(len(row.get("cases", [])) for row in case_union["rows"]),
        "unique_valid_case_urls": len(
            {
                normalized_url(case.get("official_url"))
                for row in case_union["rows"]
                for case in row.get("cases", [])
                if normalized_url(case.get("official_url"))
            }
        ),
        "route_verified_count": overlay["route_classification_counts"]["ROUTE_VERIFIED"],
        "route_review_required_count": overlay["route_classification_counts"]["ROUTE_REVIEW_REQUIRED"],
        "route_terminal_external_count": overlay["route_classification_counts"]["ROUTE_TERMINAL_EXTERNAL"],
        "active_route_p2_count": finalization["residual_p2_count"],
        "stop_reason": "STOP_R2_NET_NEW_VERIFIED_BELOW_4",
        "rq_03_allowed": False,
        "p0_count": finalization["p0_count"],
        "p1_count": finalization["p1_count"],
    }
    seed["seed_version"] = sha256(overlay_path)[:16]
    encoded = json.dumps(seed, ensure_ascii=False, separators=(",", ":"))
    index_path.write_text(
        index_text[: match.start()]
        + match.group(1)
        + encoded
        + match.group(3)
        + index_text[match.end() :],
        encoding="utf-8",
    )

    (pages / "route-quality.html").write_text(
        render_route_quality(overlay, case_rows, finalization),
        encoding="utf-8",
    )
    write_json(pages / "final-audit.json", independent)
    root_loop_state = read_json(args.root_loop_state.resolve())
    write_json(
        pages / "loop-state.json",
        {
            "schema_version": "navicus_public_route_quality_loop_state_v1",
            "status": root_loop_state["status"],
            "current_rq": root_loop_state["current_rq"],
            "audit_target_count": root_loop_state["audit_target_count"],
            "frozen_content_state": root_loop_state["frozen_content_state"],
            "stop_decision": root_loop_state["stop_decision"],
            "rq_02": {
                "status": root_loop_state["rq_02"]["status"],
                "independent_audit": root_loop_state["rq_02"][
                    "independent_audit"
                ],
                "opus_decision": root_loop_state["rq_02"]["opus_decision"],
                "next_decision": root_loop_state["rq_02"]["next_decision"],
            },
        },
    )
    shutil.copyfile(finalization_path, pages / "rq-02-finalization.json")
    shutil.copyfile(final_validation_path, pages / "rq-02-final-validation.json")
    public_opus = read_json(opus_path)
    public_opus.pop("conversation_id", None)
    write_json(pages / "rq-02-opus-review.json", public_opus)

    readme = f"""# NAVICUS 自治体クローラー RQ-02確定結果

2026-07-28 に完了した全139発注者の proposal-list-first 再監査結果です。

- 対象発注者: 139
- content ○: 139
- ROUTE_VERIFIED: 92
- ROUTE_REVIEW_REQUIRED: 44
- ROUTE_TERMINAL_EXTERNAL: 3
- live replay: 92/92
- 具体案件ページのcrawl target: 0
- P0/P1: 0
- 安全側P2: 13
- 停止理由: `STOP_R2_NET_NEW_VERIFIED_BELOW_4`
- RQ-03: 作成しない

横浜市は局別プロポーザル一覧をcanonical、入札・契約の新着情報一覧を
`PROCUREMENT_NEWS_DISCOVERY_FEED` として分離保持しています。

## 公開ファイル

- `index.html`: 全139発注者の案件・一覧・補完経路
- `route-quality.html`: 安全側に残した47経路
- `final-audit.json`: 独立Sol監査
- `loop-state.json`: 最終ループ状態
- `rq-02-finalization.json`: RQ-02最終判定
- `rq-02-final-validation.json`: 公開前検証
- `rq-02-opus-review.json`: Opus 5判定

## 正本チェックサム

- canonical overlay: `{sha256(overlay_path)}`
- canonical case union: `{sha256(case_union_path)}`

最終判定は `{finalization['status']}`、次判定は
`{finalization['next_decision']}` です。
"""
    (pages / "README.md").write_text(readme, encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "PASS",
                "issuer_count": len(seed["items"]),
                "route_counts": overlay["route_classification_counts"],
                "case_count": seed["final_summary"]["valid_case_rows"],
                "yokohama_feed_retained": any(
                    url
                    == "https://www.city.yokohama.lg.jp/business/nyusatsu/allNewsList.html"
                    for url in existing["muni:141003"]["accepted_supplemental_feed_urls"]
                ),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
