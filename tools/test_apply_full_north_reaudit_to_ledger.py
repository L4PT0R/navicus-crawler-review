import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("apply_full_north_reaudit_to_ledger.py")
SPEC = importlib.util.spec_from_file_location("apply_full_north_reaudit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def group(errors=None):
    return {
        "schema_version": "navicus_full_north_reaudit_group_v1",
        "items": [{
            "issuer_id": "a", "display_name": "A", "observed_at": "2026-07-31",
            "root_url": "https://a.example/list", "branches": [{"url": "https://a.example/list", "role": "proposal_list"}],
            "visible_row_count": 2, "case_count": 1, "exclusion_count": 1,
            "row_conservation_pass": True, "public_end": True, "errors": errors or [],
            "cases": [{"title": "新案件", "official_url": "https://a.example/case", "source_list_url": "https://a.example/list"}],
            "exclusions": [{"title": "結果", "url": "https://a.example/result", "reason": "result_update_not_case"}],
        }],
    }


def seed():
    return {"items": [{
        "issuer_id": "a", "cases": [
            {"title": "旧サンプル", "official_url": "https://a.example/old", "source_list_url": "https://a.example/list"},
            {"title": "別経路履歴", "official_url": "https://a.example/other", "source_list_url": "https://a.example/other-list"},
        ],
        "official_routes": [{"url": "https://a.example/old", "kind": "case_detail"}],
        "evidence": {},
    }]}


def test_complete_item_replaces_root_samples_and_conserves_exclusion():
    updated, receipt = MODULE.apply_groups(seed(), [group()])
    item = updated["items"][0]
    assert [case["title"] for case in item["cases"]] == ["別経路履歴", "新案件"]
    assert item["north_audit"]["official_case_count"] == 1
    assert item["north_audit"]["excluded_row_count"] == 1
    assert item["proposal_list_audit"]["row_conservation_pass"] is True
    assert receipt["completed_issuer_count"] == 1
    assert receipt["status"] == "NO-GO"
    assert updated["publication_gate"]["publish_allowed"] is False


def test_p0_item_is_rejected_without_mutating_issuer():
    original = seed()
    updated, receipt = MODULE.apply_groups(original, [group(["P0: incomplete denominator"])])
    assert updated["items"][0]["cases"] == original["items"][0]["cases"]
    assert updated["items"][0]["assessment"] == "triangle"
    assert updated["items"][0]["route_quality"] == "FULL_REAUDIT_BLOCKED"
    assert receipt["accepted_in_this_run"] == 0
    assert receipt["rejected_issuer_count"] == 1


def test_unmaterialized_rows_require_explicit_operator_exception():
    candidate = group()
    candidate["items"][0]["unmaterialized_terminal_rows"] = [{"ordinal": 1}]
    updated, receipt = MODULE.apply_groups(seed(), [candidate])
    assert updated["items"][0]["cases"] == seed()["items"][0]["cases"]
    assert updated["items"][0]["assessment"] == "triangle"
    assert "unmaterialized_terminal_rows_not_operator_approved:1" in receipt["rejected"]["a"]


def test_ishikawa_and_kanazawa_are_the_only_approved_unmaterialized_terminals():
    candidate = group()
    candidate["items"][0]["issuer_id"] = "shared:17:ishikawa_portal_discovery"
    candidate["items"][0]["unmaterialized_terminal_rows"] = [{"ordinal": 1}]
    source = seed()
    source["items"][0]["issuer_id"] = "shared:17:ishikawa_portal_discovery"
    updated, receipt = MODULE.apply_groups(source, [candidate])
    assert receipt["accepted_in_this_run"] == 1
    assert updated["items"][0]["route_quality"] == "VERIFIED_FULL_LIST_REAUDIT"


def test_reapplying_same_group_is_case_idempotent():
    once, _ = MODULE.apply_groups(seed(), [group()])
    twice, _ = MODULE.apply_groups(once, [group()])
    assert [case["title"] for case in once["items"][0]["cases"]] == [
        case["title"] for case in twice["items"][0]["cases"]
    ]


def test_legacy_route_path_shapes_are_normalized_to_arrays():
    candidate = group()
    candidate["items"][0]["cases"][0]["route_path"] = {"url": "https://a.example/list"}
    updated, _ = MODULE.apply_groups(seed(), [candidate])
    route_path = next(case for case in updated["items"][0]["cases"] if case["title"] == "新案件")["route_path"]
    assert route_path == [{"url": "https://a.example/list"}]


def test_retained_legacy_route_path_is_also_normalized():
    source = seed()
    source["items"][0]["cases"][1]["route_path"] = "https://a.example/other-list"
    updated, _ = MODULE.apply_groups(source, [group()])
    retained = next(case for case in updated["items"][0]["cases"] if case["title"] == "別経路履歴")
    assert retained["route_path"] == ["https://a.example/other-list"]
