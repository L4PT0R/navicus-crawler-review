#!/usr/bin/env python3
"""Publish a sanitized NAVICUS watchdog snapshot for GitHub Pages.

The watchdog source contains local paths, thread identifiers, and hash receipts.
This exporter intentionally publishes only the decision state, gate counts, and
next observation condition needed by dashboard viewers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def public_status(source: dict[str, Any], rq02: dict[str, Any]) -> dict[str, Any]:
    if source.get("schema_version") != "navicus_loop_watchdog_latest_status_v1":
        raise SystemExit("unsupported watchdog schema")

    loop_b = source.get("latest_loop_b_gate", {})
    a_parent = source.get("a_parent_v8_partial_acceptance", {})
    a_acceptance = source.get("a_live_v8_independent_acceptance", {})
    transport = source.get("latest_transport_v3_gate", {})
    final_gate = source.get("latest_final_gate", {})
    route_counts = a_parent.get("route_status_counts", {})
    waiting = source.get("justified_waiting", [])
    next_observation_at = waiting[0].get("not_before") if waiting else None

    return {
        "schema_version": "navicus_public_loop_status_v1",
        "updated_at": source.get("updated_at"),
        "overall": {
            "decision": "NO_GO",
            "stop_gate": source.get("stop_gate", "UNKNOWN"),
            "label": "最終公開ゲート未達",
            "detail": "RQ-02正本は完了。後続の回復ループは追加観測と最終QA待ちです。",
        },
        "rq02": {
            "status": rq02.get("rq_02", {}).get("status", "UNKNOWN"),
            "circle": rq02.get("frozen_content_state", {}).get("circle"),
            "target": rq02.get("audit_target_count"),
            "decision": rq02.get("rq_02", {}).get("opus_decision"),
        },
        "gates": [
            {
                "id": "A",
                "label": "経路回復・再観測",
                "status": "WAITING",
                "decision": a_parent.get("overall_decision", "UNKNOWN"),
                "blocked": route_counts.get("BLOCKED"),
                "needs_second_observation": route_counts.get(
                    "NEEDS_SECOND_OBSERVATION"
                ),
                "severity": a_acceptance.get("severity_counts", {}),
                "detail": "オフライン再固定は受入済み。live実行は未承認です。",
            },
            {
                "id": "B",
                "label": "独立監査",
                "status": "GO" if loop_b.get("decision") == "GO" else "BLOCKED",
                "decision": loop_b.get("decision", "UNKNOWN"),
                "severity": loop_b.get("severity_counts", {}),
                "detail": "最新の独立監査世代を採用しています。",
            },
            {
                "id": "T",
                "label": "Transport契約",
                "status": "GO_LIMITED",
                "decision": transport.get("decision", "UNKNOWN"),
                "severity": source.get("a_live_v8_independent_acceptance", {}).get(
                    "severity_counts", {}
                ),
                "detail": "認可ハンドシェイクの再固定までGO。live GETの許可ではありません。",
            },
            {
                "id": "F",
                "label": "最終統合・公開判定",
                "status": "BLOCKED",
                "decision": final_gate.get("status", "UNKNOWN"),
                "detail": "baseline、差分評価、最終QAの完了前はGOへ昇格しません。",
            },
        ],
        "next_action": {
            "next_observation_at": next_observation_at,
            "conditions": [
                "第2観測時刻の到来",
                "新しい受入済み経路証拠",
                "operator承認とmeter再確認",
                "最終QAでP0/P1ゼロを確認",
            ],
        },
        "history": [
            {
                "at": "2026-07-28T20:33:18+09:00",
                "status": "DONE",
                "title": "RQ-02を正本化",
                "detail": "139発注者の内容判定を139/139○で確定し、RQ-03は作成しない停止判定を採用。",
            },
            {
                "at": "2026-07-29T21:12:38+09:00",
                "status": "START",
                "title": "Loop Watchdogを開始",
                "detail": "A・B・Transport・Finalを分離監視。全体GOを出さず、未完了ゲートの追跡を開始。",
            },
            {
                "at": "2026-07-29T21:18:00+09:00",
                "status": "SUPERSEDED",
                "title": "Loop Bの旧世代をNO-GO",
                "detail": "P1が残る旧監査世代を不採用とし、世代固定と独立再監査へ戻した。",
            },
            {
                "at": "2026-07-29T21:19:00+09:00",
                "status": "REPAIR",
                "title": "Loop Aの修復条件を固定",
                "detail": "runtime配線・Transport契約・改変耐性をP1として検出し、offline修復を継続。",
            },
            {
                "at": "2026-07-29T21:56:00+09:00",
                "status": "DONE",
                "title": "Loop B独立監査がGO",
                "detail": "最新世代でP0/P1/P2ゼロを確認し、旧NO-GOをsupersede。",
            },
            {
                "at": "2026-07-29T23:38:00+09:00",
                "status": "PARTIAL_GO",
                "title": "Loop A v8部分ゲートを受入",
                "detail": "独立検査22/22、回帰77/77。P0/P1ゼロ、非blocking P2が1件。全体GOには昇格せず。",
            },
            {
                "at": "2026-07-29T23:55:00+09:00",
                "status": "BLOCKED",
                "title": "最終preflightをNO-GOで固定",
                "detail": "125経路BLOCKED、4経路は第2観測待ち。baseline・差分評価・最終QAの完了前は公開GOにしない。",
            },
            {
                "at": source.get("updated_at"),
                "status": "CURRENT",
                "title": "監視継続・状態変化なし",
                "detail": "offline工程は完了。第2観測時刻、新しい経路証拠、operator承認のいずれかを待機。",
            },
        ],
        "safety": {
            "watchdog_live_gets": source.get("safety", {}).get(
                "watchdog_live_gets"
            ),
            "meter_or_24h_bypass": source.get("safety", {}).get(
                "meter_or_24h_bypass"
            ),
            "operator_approval_invented": source.get("safety", {}).get(
                "operator_approval_invented"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchdog", required=True, type=Path)
    parser.add_argument("--rq02-state", required=True, type=Path)
    parser.add_argument("--out", default=Path("loop-status.json"), type=Path)
    args = parser.parse_args()

    result = public_status(read_json(args.watchdog), read_json(args.rq02_state))
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
