# NAVICUS 自治体クローラー RQ-02確定結果

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
- `status.html`: RQ-02確定結果、後続回復ループの現在ゲート、今回の時系列
- `loop-status.json`: 内部識別子を除外した公開用ループ状態
- `route-quality.html`: 安全側に残した47経路
- `final-audit.json`: 独立Sol監査
- `loop-state.json`: 最終ループ状態
- `rq-02-finalization.json`: RQ-02最終判定
- `rq-02-final-validation.json`: 公開前検証
- `rq-02-opus-review.json`: Opus 5判定

## 正本チェックサム

- canonical overlay: `5bf3870733d516ee65ac7b296478458886100749a8ad5db57ff66fbb790e5208`
- canonical case union: `30571503d12e1d6afa1a6846a398dfa4397e96045c4e0ca766d37394760775a3`

最終判定は `GO_CANONICAL_STOP`、次判定は
`STOP_NO_RQ_03` です。

## 2026-07-29 スコープ修正

- RQ-02の内容判定 **139 / 139 ○** を確定結果として維持します。
- 後続ループの `0 / 1,741`、全年度・全部局分母の証明、137件P0は、
  依頼範囲を過剰拡張したため次フェーズの阻害条件から撤回しました。
- 完了単位は、自治体ごとに確認した公式プロポーザル集約一覧面です。
  その一覧に表示された案件をすべて枝葉化し、一覧自身にページネーションが
  ある場合だけ最終ページまで追跡します。
- 東京・政令指定都市のゼロトークンクローラーフェーズへ移行しました。
  町・村は対象外です。

機械可読な修正内容は `scope-correction.json` にあります。

## ループ状態の更新

監視正本から公開可能な判定・件数だけを抽出します。内部スレッドID、
ローカルパス、SHA receiptは公開しません。

```bash
python tools/publish_loop_status.py \
  --watchdog ../../work/crawler_recovery_2026-07-29/loop_watchdog/latest_status.json \
  --rq02-state loop-state.json \
  --out loop-status.json
```
