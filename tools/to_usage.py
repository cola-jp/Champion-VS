# -*- coding: utf-8 -*-
"""champs.pokedb.tokyo の抽出結果を、既存の generate.py が読める形に変換する。

pkmnchamps の usage.json とは違い、名前は日本語・能力ポイントはポイント単位。
そのぶん英語スラッグの和訳も EV 換算も要らないが、表記ゆれの吸収が必要になる。
"""
import json
import re
import sys
import unicodedata

import os
# リポジトリでは build/ 配下。claude.ai 用スキルのバンドルでは scripts/ になる
_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in ('build', 'scripts'):
    _p = os.path.join(os.path.dirname(_HERE), _d)
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
import engine as E

# サイト表記 → 図鑑表記。機械的な規則で吸収できないものだけ書く
NAME_FIX = {
    'イダイトウ (オス)': 'イダイトウ♂', 'イダイトウ (メス)': 'イダイトウ♀',
    'イエッサン (オス)': 'イエッサン♂', 'イエッサン (メス)': 'イエッサン♀',
    'フラエッテ:永遠': 'フラエッテ(えいえん)',
    'ケンタロス:炎': 'ケンタロス(パルデア炎)',
    'ケンタロス:水': 'ケンタロス(パルデア水)',
    'ケンタロス:単': 'ケンタロス(パルデア単)',
    # フォルムが分かれているが使用率は合算で出るもの。主形態に寄せる
    'ギルガルド': 'ギルガルド(ブレード)',
    'イルカマン': 'イルカマン(マイティ)',
}


def norm_name(name):
    """「キュウコン (アローラ)」→「キュウコン(アローラ)」のように空白を詰めて図鑑名に合わせる。"""
    n = unicodedata.normalize('NFKC', name).strip()
    if n in NAME_FIX:
        return NAME_FIX[n]
    n2 = re.sub(r'\s*\(\s*', '(', n)
    n2 = re.sub(r'\s*\)', ')', n2)
    if n2 in NAME_FIX:
        return NAME_FIX[n2]
    return n2


def norm_item(item):
    """「ガブリアスナイトＺ」の全角Ｚなどを半角に寄せる。メガの判定が endswith('Z') のため必須。"""
    return unicodedata.normalize('NFKC', item).strip()


def norm_move(name):
    """「１０まんボルト」「ＤＤラリアット」の全角英数を半角に寄せる。"""
    return unicodedata.normalize('NFKC', name).strip()


def convert(parsed, season='不明'):
    out = []
    for p in parsed:
        name = norm_name(p['name'])
        if name not in E.DEX:
            print(f'  警告: 図鑑に無い「{p["name"]}」→「{name}」 順位{p["pick_rank"]}')
            continue
        if not p['moves']:
            print(f'  データなしのため除外: {name} 順位{p["pick_rank"]}')
            continue
        sps_list = []
        for sp in p['spreads']:
            pts = {k: 0 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')}
            pts.update(sp['points'])
            sps_list.append({'sps': pts, 'usage': sp['usage'], 'label': sp['label']})
        out.append({
            'pick_rank': p['pick_rank'],
            # どのシーズンのデータかを1件ずつに持たせる。旧データの 'month' と同じ役目で、
            # consult.py の見出しと make_skill.py の表示がこれを読む。
            # 無いと「不明」と出るだけで止まらないので、渡し忘れに気づけるようにしている。
            'season': season,
            # generate.py の resolve_form はこのキーがあれば pokemon_id 逆引きを飛ばす
            'dex_name': name,
            'pokemon_id': None,
            'region_form': '',
            'mega_form': '',
            'pokemon_name_ko': name,
            'name': name,
            'moves': [{'name': norm_move(m['name']), 'usage': m['usage']} for m in p['moves']],
            'abilities': p['abilities'],
            'items': [{'name': norm_item(i['name']), 'usage': i['usage']} for i in p['items']],
            'natures': p['natures'],
            'spreads': sps_list,
            'teammates': p['teammates'],
        })
    out.sort(key=lambda x: x['pick_rank'])
    return out


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit('usage: python tools/to_usage.py parsed.json data/usage.json [シーズン名]')
    parsed = json.load(open(sys.argv[1], encoding='utf-8'))
    data = convert(parsed, sys.argv[3] if len(sys.argv) > 3 else '不明')
    json.dump(data, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'{len(data)}件を書き出した')
