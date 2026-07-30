import importlib.util
import json
import subprocess
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("publish_rq02.py")
SPEC = importlib.util.spec_from_file_location("publish_rq02", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_dashboard_preserves_issuer_list_position_when_opening_detail() -> None:
    html = MODULE_PATH.parent.parent.joinpath("index.html").read_text(encoding="utf-8")
    assert "function captureListPosition()" in html
    assert "function restoreListPosition(restoreWindow = false)" in html
    assert "captureListPosition();" in html
    assert "restoreListPosition(false);" in html
    assert "restoreListPosition(true);" in html
    assert "window.scrollTo(0, listWindowScrollY);" in html


def test_merge_preserves_source_case_when_rq02_is_empty() -> None:
    source = [
        {
            "title": "企画提案募集",
            "official_url": "https://example.jp/case/1",
            "summary": "source summary",
        }
    ]
    assert MODULE.merge_cases(source, []) == source


def test_merge_enriches_without_deleting_source_fields() -> None:
    source = [
        {
            "title": "企画提案募集",
            "official_url": "https://example.jp/case/1",
            "summary": "source summary",
            "route_path": [{"url": "https://example.jp/list"}],
        }
    ]
    rq02 = [
        {
            "title": "企画提案募集",
            "official_url": "https://example.jp/case/1",
            "observed_at": "2026-07-30",
            "summary": "",
        }
    ]
    merged = MODULE.merge_cases(source, rq02)
    assert len(merged) == 1
    assert merged[0]["summary"] == "source summary"
    assert merged[0]["route_path"] == [{"url": "https://example.jp/list"}]
    assert merged[0]["observed_at"] == "2026-07-30"


def test_title_fallback_is_deterministic() -> None:
    assert MODULE.case_key({
        "title": "  公募型  企画提案 ",
        "official_url": "https://example.jp/list/",
    }) == "url-title:https://example.jp/list\0公募型 企画提案"


def test_case_id_is_the_primary_logical_key() -> None:
    assert MODULE.case_key({"case_id": "case-1"}) == "id:case-1"


def test_merge_preserves_duplicate_source_rows() -> None:
    source = [
        {"title": "募集", "official_url": "https://example.jp/case/1", "status": "公告"},
        {"title": "結果", "official_url": "https://example.jp/case/1", "status": "結果"},
    ]
    rq02 = [
        {"title": "募集", "official_url": "https://example.jp/case/1", "observed_at": "2026-07-30"}
    ]
    merged = MODULE.merge_cases(source, rq02)
    assert len(merged) == 2
    by_title = {case["title"]: case for case in merged}
    assert by_title["募集"]["status"] == "公告"
    assert by_title["募集"]["observed_at"] == "2026-07-30"
    assert by_title["結果"]["status"] == "結果"
    assert "observed_at" not in by_title["結果"]


def test_distinct_case_ids_survive_same_url_and_title() -> None:
    rows = [
        {"case_id": "case-a", "title": "募集", "official_url": "https://example.jp/list"},
        {"case_id": "case-b", "title": "募集", "official_url": "https://example.jp/list"},
    ]
    merged = MODULE.merge_cases([], rows)
    assert {case["case_id"] for case in merged} == {"case-a", "case-b"}


def test_no_id_alias_merges_into_single_matching_case_id() -> None:
    rows = [
        {"title": "募集", "official_url": "https://example.jp/list", "summary": "review"},
        {"case_id": "case-a", "title": "募集", "official_url": "https://example.jp/list"},
    ]
    merged = MODULE.merge_cases([], rows)
    assert len(merged) == 1
    assert merged[0]["case_id"] == "case-a"
    assert merged[0]["summary"] == "review"


def test_recovery_case_builds_route_path_from_current_list() -> None:
    row = MODULE.recovery_case_for_dashboard({
        "case_id": "case-1",
        "title": "公募型プロポーザル",
        "summary": "公式一覧から取得",
        "official_url": "https://city.example.jp/detail/1",
        "source_list_url": "https://city.example.jp/list",
        "observed_at": "2026-07-30T12:00:00+09:00",
        "proposal_basis": "official_list_title_contains:プロポーザル",
    })
    assert row["official_url"] == "https://city.example.jp/detail/1"
    assert row["case_id"] == "case-1"
    assert [node["surface_role"] for node in row["route_path"]] == ["proposal_list", "case_detail"]
    assert row["proposal_basis"]


def test_recovery_merge_preserves_distinct_cases_sharing_one_list_url() -> None:
    rows = [
        {"case_id": "case-a", "title": "グランドデザイン", "official_url": "https://example.jp/list"},
        {"case_id": "case-b", "title": "メディアプロモーション", "official_url": "https://example.jp/list"},
    ]
    merged = MODULE.merge_recovery_cases([], rows)
    assert len(merged) == 2
    assert {row["case_id"] for row in merged} == {"case-a", "case-b"}


def test_recovery_merge_is_idempotent_by_case_id() -> None:
    rows = [
        {"case_id": "case-a", "title": "案件A", "official_url": "https://example.jp/list"},
        {"case_id": "case-b", "title": "案件B", "official_url": "https://example.jp/list"},
    ]
    once = MODULE.merge_recovery_cases([], rows)
    twice = MODULE.merge_recovery_cases(once, rows)
    assert twice == once


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _dashboard_html(container_id: str, seed: dict) -> str:
    encoded = json.dumps(seed, ensure_ascii=False, separators=(",", ":"))
    return (
        '<!doctype html><section class="phase-banner"><strong>old</strong></section>'
        f'<script id="{container_id}" type="application/json">{encoded}</script>'
    )


def _build_cli_fixture(tmp_path: Path) -> dict[str, Path]:
    rq02 = tmp_path / "rq02"
    (rq02 / "independent_audit").mkdir(parents=True)
    issuer_ids = ["muni:141003", *[f"muni:{index:06d}" for index in range(1, 139)]]
    template_items = []
    source_a_items = []
    source_b_items = []
    overlay_items = []
    case_rows = []
    for index, issuer_id in enumerate(issuer_ids):
        url = f"https://example.jp/cases/{index}"
        base_case = {"title": f"案件 {index}", "official_url": url}
        template_items.append({
            "issuer_id": issuer_id,
            "public_body_code": str(index),
            "region": "test",
            "prefecture": "test",
            "display_name": issuer_id,
            "roles": [],
            "priority": "P2",
            "batch_id": "fixture",
            "cases": [base_case],
        })
        source_a_items.append({"issuer_id": issuer_id, "cases": [base_case]})
        source_b_cases = [dict(base_case)]
        if index == 0:
            source_b_cases.append({"title": "同一URLの別案件", "official_url": url})
        source_b_items.append({"issuer_id": issuer_id, "cases": source_b_cases})
        if index < 92:
            classification = "ROUTE_VERIFIED"
        elif index < 136:
            classification = "ROUTE_REVIEW_REQUIRED"
        else:
            classification = "ROUTE_TERMINAL_EXTERNAL"
        overlay_items.append({
            "issuer_id": issuer_id,
            "display_name": issuer_id,
            "canonical_route_classification": classification,
            "canonical_crawl_target_url": None,
            "accepted_supplemental_feed_urls": (
                ["https://www.city.yokohama.lg.jp/business/nyusatsu/allNewsList.html"]
                if issuer_id == "muni:141003"
                else []
            ),
            "normalized_url_union": [],
            "blocker": None,
            "next_hypothesis": "fixture",
        })
        case_rows.append({
            "issuer_id": issuer_id,
            "cases": [],
            "invalid_cases": [],
            "alternate_official_evidence": [],
        })

    template_seed = {"items": template_items}
    source_a = tmp_path / "source-a.html"
    source_b = tmp_path / "source-b.html"
    source_a.write_text(
        _dashboard_html("seed-data", {"items": source_a_items}), encoding="utf-8"
    )
    source_b.write_text(
        _dashboard_html("payload", {"items": source_b_items}), encoding="utf-8"
    )
    template = tmp_path / "template.html"
    template.write_text(_dashboard_html("seed-data", template_seed), encoding="utf-8")

    _write_json(rq02 / "canonical_overlay.json", {
        "items": overlay_items,
        "issuer_count": 139,
        "route_classification_counts": {
            "ROUTE_VERIFIED": 92,
            "ROUTE_REVIEW_REQUIRED": 44,
            "ROUTE_TERMINAL_EXTERNAL": 3,
        },
    })
    _write_json(rq02 / "canonical_case_union.json", {"rows": case_rows})
    _write_json(rq02 / "finalization.json", {
        "finalized_at": "2026-07-30T00:00:00+09:00",
        "residual_p2_count": 47,
        "p0_count": 0,
        "p1_count": 0,
        "status": "fixture",
        "next_decision": "fixture",
    })
    _write_json(rq02 / "final_validation.json", {})
    _write_json(rq02 / "independent_audit" / "independent_audit_result.json", {})
    _write_json(rq02 / "opus_review_result.json", {"conversation_id": "removed"})

    root_loop_state = tmp_path / "root-loop-state.json"
    _write_json(root_loop_state, {
        "status": "fixture",
        "current_rq": 2,
        "audit_target_count": 139,
        "frozen_content_state": {"circle": 139, "triangle": 0},
        "stop_decision": "fixture",
        "rq_02": {
            "status": "fixture",
            "independent_audit": {},
            "opus_decision": "fixture",
            "next_decision": "fixture",
        },
    })
    recovery = tmp_path / "recovery.json"
    _write_json(recovery, {
        "items": [
            {
                "issuer_id": issuer_id,
                "verified_zero": False,
                "cases": [{
                    "case_id": f"recovery-{index}",
                    "title": f"回復案件 {index}",
                    "official_url": f"https://example.jp/recovery/{index}",
                }],
            }
            for index, issuer_id in enumerate(issuer_ids[:70])
        ]
    })
    return {
        "rq02": rq02,
        "root_loop_state": root_loop_state,
        "recovery": recovery,
        "source_a": source_a,
        "source_b": source_b,
        "template": template,
    }


def _run_cli(fixture: dict[str, Path], pages: Path, sources: list[Path]) -> None:
    pages.mkdir(exist_ok=True)
    if not (pages / "index.html").exists():
        (pages / "index.html").write_bytes(fixture["template"].read_bytes())
    command = [
        sys.executable,
        str(MODULE_PATH),
        "--rq02",
        str(fixture["rq02"]),
        "--root-loop-state",
        str(fixture["root_loop_state"]),
    ]
    for source in sources:
        command.extend(["--case-source-html", str(source)])
    command.extend([
        "--recovery-overlay-json",
        str(fixture["recovery"]),
        "--pages-root",
        str(pages),
    ])
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_read_dashboard_seed_accepts_payload(tmp_path: Path) -> None:
    path = tmp_path / "payload.html"
    path.write_text(
        _dashboard_html("payload", {"items": [{"issuer_id": "muni:1", "cases": []}]}),
        encoding="utf-8",
    )
    assert MODULE.read_dashboard_seed(path)["items"][0]["issuer_id"] == "muni:1"


def test_full_cli_is_order_independent_and_twice_idempotent(tmp_path: Path) -> None:
    fixture = _build_cli_fixture(tmp_path)
    pages_ab = tmp_path / "pages-ab"
    pages_ba = tmp_path / "pages-ba"
    _run_cli(fixture, pages_ab, [fixture["source_a"], fixture["source_b"]])
    first = (pages_ab / "index.html").read_bytes()
    _run_cli(fixture, pages_ab, [fixture["source_a"], fixture["source_b"]])
    second = (pages_ab / "index.html").read_bytes()
    _run_cli(fixture, pages_ba, [fixture["source_b"], fixture["source_a"]])
    reversed_sources = (pages_ba / "index.html").read_bytes()
    assert first == second == reversed_sources

    seed = MODULE.read_dashboard_seed(pages_ab / "index.html")
    assert seed["publication_gate"]["decision"] == "GO"
    assert seed["publication_gate"]["publish_allowed"] is True
    assert sum(len(item["cases"]) for item in seed["items"]) == 210
    first_issuer = next(item for item in seed["items"] if item["issuer_id"] == "muni:141003")
    assert len(first_issuer["cases"]) == 3
    assert {case["title"] for case in first_issuer["cases"]} == {
        "案件 0",
        "同一URLの別案件",
        "回復案件 0",
    }
    assert "公開判定：GO" in (pages_ab / "index.html").read_text(encoding="utf-8")


def test_public_dashboard_renders_crawl_roots_before_case_branches() -> None:
    dashboard = MODULE_PATH.parent.parent / "index.html"
    text = dashboard.read_text(encoding="utf-8")
    assert "クロールした大元" in text
    assert 'crawl_root:"クロール起点"' in text
    assert "typeof raw===\"string\"" in text
    assert "c.source_list_url" in text
    assert "rootRegister" in text
