# Champion-VS

ポケモンチャンピオンズ（レギュレーションM-B シングル）の対面ダメージ表。

**https://cola-jp.github.io/Champion-VS/**

相手のポケモン名を数文字打つと、自分のパーティ全員の最大打点・確定何発・被弾がまとめて出る。
対戦中にスマホやサブモニタで開く用途。オフラインでも動く単一HTML。

## ビルド

```bash
pip install openpyxl
python build/generate.py
```

`index.html` が上書きされる。生成物なので直接編集しない。

## パーティを変更する

`build/party.py` の `PARTY` を編集してビルドし直す。
`ev` は能力ポイント表記（1ポイント = 努力値8、合計66まで）。

メガ形態は `species` にメガ側の名前（例: `メガギャラドス`）を指定すること。
ゲーム内のステータス画面はメガシンカ前の数値を表示するので、そのまま写すと間違える。
generate.py が実数値を自動検証するので、設定ミスならビルドが止まる。

## データを更新する

1. `data/技使用率データ.JSON` を新しい月のものに差し替える。
   取得元は pkmnchamps.com のAPIレスポンス
   （`action=list&regulation=reg_mb&month=YYYY-MM&format=singles`）。
   ブラウザで開いて保存すればよい。自動取得の仕組みは無い。
2. `python build/generate.py` を実行する。
3. 警告（`data/move_names_en_ja.json に無い技があります`）が出たら、該当の技を
   `data/move_names_en_ja.json` に追記する（英語技名 → 日本語技名）。
   ビルドがエラーで止まった場合（図鑑に無いポケモン／リージョンフォーム未解決／技データに無い技）は、
   `data/ポケモン図鑑.xlsx` に該当のポケモンや技の行を追加してから再実行する。

技の日本語名は `data/move_names_en_ja.json` が一次情報なので、月が変わってもシート名を
直書きしているコードを探して回る必要はない。

新しい特性を持つポケモンが入ってくると「計算に入れるか未判断の特性があります」と警告が出る。
`data/abilities_ja.json` で効果を確認し、`build/generate.py` の `ABILITY_HANDLING` に
反映するのか無視するのかを1行足す。

## 特性データを更新する

`data/特性の効果.pdf`（育成考察Wikiの特性一覧ページ）を新しいものに置き換えて、

```bash
pip install pypdf
python build/extract_abilities.py
```

`data/abilities_ja.json` が作り直される。通常のビルドには pypdf は要らない。

## 公開

main ブランチのルートを GitHub Pages が配信している。
`index.html` を push すれば1〜3分で反映される。URLは変わらない。

## 詳細

設計上の判断と、間違えやすいドメイン知識は `CLAUDE.md` に書いてある。
