#!/usr/bin/env python3
"""
claude.ai にアップロードする Skill を組み立てる。

    python build/make_skill.py

`dist/pokemon-champions-team-building/` と、その zip を作る。
zip を claude.ai の設定からスキルとして登録すれば、普通のチャットで
このリポジトリと同じ計算ができる（claude.ai 側のコード実行環境で動く）。

**手で組み立てないこと。** 使用率データは毎月差し替わるので、手で作った
バンドルは次の月には古い数字を出す。ここから作り直せば必ず今のデータになる。
更新手順は「データを更新したらこれを流し直して上げ直す」だけ。

配置は engine.py のパス解決（ROOT = scripts の親、DATA = ROOT/data）に合わせてある。
スクリプトを scripts/ に、データを data/ に置けばコードは無改造で動く。

使用率データは原本が整形済みJSONで大きいので、詰めて書き出す（約6割減）。
中身は同じなので、計算結果は変わらない。ファイル名だけ ASCII にする
（zip に日本語名を入れると環境によっては取り出せない）。
"""
import json
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import ROOT

NAME = 'pokemon-champions-team-building'
OUT_ROOT = os.path.join(ROOT, 'dist')
OUT = os.path.join(OUT_ROOT, NAME)

# party.py は import した時点で party.txt を読み、無いと止まる。
# 既定のパーティとしても例題としても要るので、リポジトリのものをそのまま入れる。
SCRIPTS = ['engine.py', 'party.py', 'generate.py', 'consult.py', 'seed_party.py',
           'matchup.py', 'partycode.py']
DATA = ['dex.csv', 'moves.csv', 'type_chart.csv',
        'move_names_en_ja.json', 'abilities_ja.json',
        # 文字列コードの台帳。並びが意味を持つので必ず入れる
        'code_dict.json']
# zip に日本語のファイル名を入れると環境によっては化けて取り出せないので、
# 配布物では ASCII 名にする。partycode.py がこちらの名前も見るようになっている。
RENAME = {'常用漢字.txt': 'joyo.txt'}
# 使用率データは M-C からリポジトリ側も usage.json になったので、リネームは要らない。
# ただし配布物では 1行にまとめて縮めるので、単純コピーではなく詰め直す。
USAGE_SRC = USAGE_OUT = 'usage.json'


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, 'scripts'))
    os.makedirs(os.path.join(OUT, 'data'))

    src_skill = os.path.join(ROOT, 'skill', 'SKILL.md')
    if not os.path.exists(src_skill):
        sys.exit(f'{src_skill} がありません。スキルの本文はここに置いてあります。')
    shutil.copy(src_skill, os.path.join(OUT, 'SKILL.md'))
    shutil.copy(os.path.join(ROOT, 'party.txt'), os.path.join(OUT, 'party.txt'))

    for name in SCRIPTS:
        shutil.copy(os.path.join(ROOT, 'build', name),
                    os.path.join(OUT, 'scripts', name))
    for name in DATA:
        shutil.copy(os.path.join(ROOT, 'data', name),
                    os.path.join(OUT, 'data', name))
    for src, dst in RENAME.items():
        shutil.copy(os.path.join(ROOT, 'data', src), os.path.join(OUT, 'data', dst))

    with open(os.path.join(ROOT, 'data', USAGE_SRC), encoding='utf-8') as f:
        usage = json.load(f)
    with open(os.path.join(OUT, 'data', USAGE_OUT), 'w', encoding='utf-8') as f:
        json.dump(usage, f, ensure_ascii=False, separators=(',', ':'))

    zip_path = os.path.join(OUT_ROOT, NAME + '.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, _dirs, files in os.walk(OUT):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.join(NAME, os.path.relpath(full, OUT)))

    total = sum(os.path.getsize(os.path.join(b, f))
                for b, _d, fs in os.walk(OUT) for f in fs)
    # M-C から取得元が変わり、月ではなくシーズン単位になった（'season'）。旧データは 'month'
    stamps = sorted({e.get('season') or e.get('month') for e in usage} - {None})
    print(f'  展開後 {total / 1024:.0f} KB / zip {os.path.getsize(zip_path) / 1024:.0f} KB')
    print(f'  使用率データ: {stamps[-1] if stamps else "不明"}（{len(usage)}件）')
    print(f'組み立て完了: {zip_path}')
    print('  claude.ai の設定 > 機能 からスキルとして登録してください。')


if __name__ == '__main__':
    main()
