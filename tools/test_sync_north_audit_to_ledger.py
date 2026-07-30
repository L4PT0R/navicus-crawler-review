import copy
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("sync_north_audit_to_ledger.py")
SPEC = importlib.util.spec_from_file_location("sync_north_audit_to_ledger", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def fixture():
    seed = {
        "items": [
            {"issuer_id": "a", "cases": [], "official_routes": [], "evidence": {}},
            {
                "issuer_id": "b",
                "cases": [{"official_url": "https://b.example/old", "title": "過去案件"}],
                "official_routes": [],
                "evidence": {},
            },
        ]
    }
    audit = {
        "publication_status": "GO",
        "summary": {"accepted_count": 2, "blocking_count": 0},
        "items": [
            {
                "issuer_id": "a", "display_name": "A", "conclusion": "OFFICIAL_LIST_ENUMERATED",
                "root_url": "https://a.example/list/", "official_rows": 1, "details_reached": 1,
                "confidence": "high", "observed_at": "2026-07-31",
                "route": {"root": {"url": "https://a.example/", "label": "A公式"}, "branches": [{
                    "url": "https://a.example/list/", "label": "一覧", "role": "proposal_list",
                    "scanned": True, "details": [{"url": "https://a.example/case/1", "label": "案件1"}],
                }]},
            },
            {
                "issuer_id": "b", "display_name": "B", "conclusion": "EXACT_CONFIRMED",
                "root_url": "https://b.example/list", "official_rows": 0, "details_reached": 0,
                "confidence": "high", "observed_at": "2026-07-31",
                "route": {"root": {"url": "https://b.example/list", "label": "現在0件"}, "branches": [{
                    "url": "https://b.example/list", "role": "dedicated_proposal_page", "details": [
                        {"url": "https://b.example/stale", "label": "古い案件"}
                    ],
                }]},
            },
        ],
    }
    return seed, audit


def test_sync_adds_tree_and_cases_but_does_not_fabricate_zero():
    seed, audit = fixture()
    updated, receipt = MODULE.sync(seed, audit)
    a, b = updated["items"]
    assert seed["items"][0]["cases"] == []
    assert a["canonical_crawl_target_url"] == "https://a.example/list/"
    assert a["cases"][0]["title"] == "案件1"
    assert [node["url"] for node in a["route_graph"]["nodes"]] == [
        "https://a.example/list/", "https://a.example/case/1"
    ]
    assert b["evidence"]["verified_zero"] is True
    assert [case["title"] for case in b["cases"]] == ["過去案件"]
    assert all(node["url"] != "https://b.example/stale" for node in b["route_graph"]["nodes"])
    assert receipt["issuer_count"] == 2
    assert receipt["case_count_added"] == 1


def test_sync_is_idempotent_for_cases_and_routes():
    seed, audit = fixture()
    once, _ = MODULE.sync(seed, audit)
    twice, receipt = MODULE.sync(copy.deepcopy(once), audit)
    assert len(twice["items"][0]["cases"]) == 1
    assert len(twice["items"][0]["official_routes"]) == 2
    # The receipt keeps the cumulative first-sync delta while the materialized rows stay stable.
    assert receipt["before_case_count"] == 1
    assert receipt["after_case_count"] == 2
    assert receipt["case_count_added"] == 1
