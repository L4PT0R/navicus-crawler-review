# NAVICUS 自治体クローラー回復結果

公開判定は **GO** です。完全に独立したCodex新規スレッドを連鎖したGate08で公開条件を満たしました。

## 2026-07-30 三重県以南の0件回復

- 対象: 三重県〜沖縄県 70発注主体（親A 34 / 親B 36）
- 現行公式応答から回復した案件行: 2,682
- 公開台帳全体: 139発注主体 / 3,391案件行 / 空0
- `verified_zero=true`: 0
- 現行Pages・review正本に対する件数退行: 0
- 新規スレッド連鎖・最終Gate08: GO（P0=0 / P1=0 / P2=0）
- 今回の回復ループでは Opus 未使用

「今回の経過」は `status.html`、機械可読な状態は `loop-status.json` で確認できます。
全政府・全履歴の完全性は主張せず、今回観測した公式一覧面の範囲を表示します。

- 対象発注者: 139
- content ○: 139
- ROUTE_VERIFIED: 92
- ROUTE_REVIEW_REQUIRED: 44
- ROUTE_TERMINAL_EXTERNAL: 3
- live replay: 92/92
- 具体案件ページのcrawl target: 0
- 今回の公開判定: P0=0 / P1=0 / P2=0
- 安全側P2: 13
- 停止理由: `STOP_R2_NET_NEW_VERIFIED_BELOW_4`
- RQ-03: 作成しない

横浜市は局別プロポーザル一覧をcanonical、入札・契約の新着情報一覧を
`PROCUREMENT_NEWS_DISCOVERY_FEED` として分離保持しています。

## 公開ファイル

- `index.html`: 全139発注者の案件・一覧・補完経路
- `status.html`: 三重県以南の回復ループと公開ゲート
- `loop-status.json`: 公開用のループ経過
- `route-quality.html`: 安全側に残した47経路
- `final-audit.json`: 独立Sol監査
- `loop-state.json`: 最終ループ状態
- `rq-02-finalization.json`: RQ-02最終判定
- `rq-02-final-validation.json`: 公開前検証
- `rq-02-opus-review.json`: Opus 5判定

## 正本チェックサム

- canonical overlay: `5bf3870733d516ee65ac7b296478458886100749a8ad5db57ff66fbb790e5208`
- canonical case union: `30571503d12e1d6afa1a6846a398dfa4397e96045c4e0ca766d37394760775a3`

今回の回復ループは、測定・判定・修正・再測定を別々のCodex新規スレッドで連鎖し、Gate08で公開可と判定しました。
