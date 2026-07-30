import importlib.util
from pathlib import Path


PATH = Path(__file__).with_name("apply_operator_list_patch.py")
SPEC = importlib.util.spec_from_file_location("operator_patch", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_apply_conserves_cases_and_exclusions_and_draws_all_branches():
    seed = {"items": [{"issuer_id": "a", "cases": [{"title": "old"}]}]}
    patch = {"schema_version": MODULE.SCHEMA, "observed_at": "now", "items": [{
        "issuer_id": "a", "display_name": "A", "root_url": "https://a/list", "observed_at": "now",
        "visible_row_count": 2, "case_count": 1, "exclusion_count": 1,
        "row_conservation_pass": True, "public_end": True,
        "cases": [{"title": "case", "official_url": "https://a/case", "route_path": ["https://a/list", "https://a/case"]}],
        "exclusions": [{"title": "result", "url": "https://a/result", "reason": "result_update_not_case"}],
    }]}
    item = MODULE.apply(seed, patch)["items"][0]
    assert [case["title"] for case in item["cases"]] == ["case"]
    assert item["proposal_list_audit"]["visible_row_count"] == 2
    assert len(item["route_graph"]["edges"]) == 2
    assert MODULE.apply(seed, patch)["final_summary"]["valid_case_rows"] == 1


def test_apply_rejects_unconserved_rows():
    seed = {"items": [{"issuer_id": "a"}]}
    patch = {"schema_version": MODULE.SCHEMA, "items": [{"issuer_id": "a", "row_conservation_pass": False, "public_end": True}]}
    try:
        MODULE.apply(seed, patch)
    except ValueError as error:
        assert "unconserved" in str(error)
    else:
        raise AssertionError("expected ValueError")
