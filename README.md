# Champion-VS

ポケモンチャンピオンズ（レギュレーションM-B シングル）の対面ダメージ表。

**https://cola-jp.github.io/Champion-VS/**

相手のポケモン名を数文字打つと、自分のパーティ全員の最大打点・確定何発・被弾がまとめて出る。
対戦中にスマホやサブモニタで開く用途。オフラインでも動く。

- `index.html` … ダメージ表。登録したパーティで計算する
- `party.html` … パーティー登録画面。取り込み・調整・書き出し

## パーティを変更する

`party.html` を開いて編集する。`party.txt` 形式のテキストを貼り付けて取り込み、
画面上で調整して「保存」すると、ダメージ表がそのパーティで計算される。
`party.txt` としてダウンロードもできる。

実数値は**ゲーム内のステータス画面に表示される値**（メガシンカ前）をそのまま書く。
持ち物がメガストーンならメガ形態は自動で生成される。能力ポイントは実数値・種族値・性格から
逆算され、合わない値を入れるとその場でエラーになる。

リポジトリの `party.txt` は、まだ何も登録していないときに使われる既定値。

## ビルド

```bash
python build/generate.py         # データの整合性を確認
python build/export_app_data.py  # ブラウザが読む appdata/*.json を書き出す
node build/verify_engine.js      # JS版がPython版と同じ数値を出すか確認
```

一次データは全部CSVなので、追加ライブラリも Excel も要らない。

`appdata/*.json` は生成物。直接編集しない。作り直したらコミットすること
（CI がコミット済みのものと一致するかを見ている）。

## データを更新する

1. `data/技使用率データ.JSON` を新しい月のものに差し替える。
   取得元は pkmnchamps.com のAPIレスポンス
   （`action=list&regulation=reg_mb&month=YYYY-MM&format=singles`）。
   ブラウザで開いて保存すればよい。自動取得の仕組みは無い。
2. `python build/generate.py` と `python build/export_app_data.py` を実行する。
3. 警告（`data/move_names_en_ja.json に無い技があります`）が出たら、該当の技を
   `data/move_names_en_ja.json` に追記する（英語技名 → 日本語技名）。
   ビルドがエラーで止まった場合（図鑑に無いポケモン／リージョンフォーム未解決／技データに無い技）は、
   `data/dex.csv` や `data/moves.csv` に行を追加してから再実行する。

技の日本語名は `data/move_names_en_ja.json` が一次情報なので、月が変わってもシート名を
直書きしているコードを探して回る必要はない。

新しい特性を持つポケモンが入ってくると「計算に入れるか未判断の特性があります」と警告が出る。
`data/abilities_ja.json` で効果を確認し、`build/generate.py` の `ABILITY_HANDLING` に
反映するのか無視するのかを1行足す。

## 新しいポケモン・技を足す

一次データはCSVなので直接編集する。

| 追加するもの | 触るファイル |
|---|---|
| ポケモン | `data/dex.csv` に1行。特性は `/` 区切り。メガやリージョンは同じ番号で別行 |
| 技 | `data/moves.csv` に1行 + `data/move_names_en_ja.json` に英語名の対応 |
| 特性 | 名前は `dex.csv` に書く。計算に効くかは `build/generate.py` の `ABILITY_HANDLING` に1行 |

`data/dex.csv` の列は `no,name,type1,type2,abilities,hp,atk,def,spa,spd,spe`。

```
003,フシギバナ,くさ,どく,しんりょく/ようりょくそ,80,82,83,100,100,80
```

単タイプなら `type2` は空にする。タイプ名の打ち間違いや種族値の欠けは
`python build/generate.py` が名前を挙げて止める。

`data/ポケモン図鑑.xlsx` は移行元として残してあるが、コードはもう読まない。

## 特性データを更新する

`data/特性の効果.pdf`（育成考察Wikiの特性一覧ページ）を新しいものに置き換えて、

```bash
pip install pypdf
python build/extract_abilities.py
```

`data/abilities_ja.json` が作り直される。通常のビルドには pypdf は要らない。

## 公開

main ブランチのルートを GitHub Pages が配信している。
push すれば1〜3分で反映される。URLは変わらない。
`index.html` / `party.html` / `assets/` / `appdata/` が揃っている必要がある。

## 詳細

設計上の判断と、間違えやすいドメイン知識は `CLAUDE.md` に書いてある。
