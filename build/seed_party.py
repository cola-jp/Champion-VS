#!/usr/bin/env python3
"""
使用率データから party.txt のブロックを起こす。

    python build/seed_party.py メガスターミー メガメガニウム:HC > core.txt

まだ育てていないポケモンを軸に構築を考えるとき、実数値・性格・特性・持ち物・技を
手で調べて書くのが面倒で、しかも書き間違える。環境で実際に使われている型が
使用率データに入っているので、そこから起こしてしまう。

`名前:型` で配分パターンを指定できる（`HC`、`AS` など）。省略すると採用率が最も高い型。
出てくるのはあくまで**環境の最頻値**なので、そこから調整する叩き台として使う。

実数値は party.txt の約束どおり**メガシンカ前**（ゲーム内のステータス画面の値）で出す。
メガ形態を指定した場合は持ち物にメガストーンが入るので、計算側が勝手にメガ形態を作る。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import DEX, MOVES, USAGE, NAT_JA, resolve_form, stats
from generate import (spread_variants, pick_nature, pick_form, translate_moves,
                      ITEM_JA, ABILITY_JA, _is_stone)

STAT_KEYS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']


def find_entry(name):
    """図鑑名から使用率データのエントリを探す。メガ形態の名前でも通常形態の名前でも引ける。"""
    for e in USAGE:
        base, megas = resolve_form(e)
        if name == base or name in megas:
            return e, base, megas
    return None, None, None


def block(name, pattern=None):
    e, base, megas = find_entry(name)
    if e is None:
        sys.exit(f'{name}: 使用率データに見つかりません。'
                 f'（環境上位にしか居ないので、圏外のポケモンは手で書いてください）')

    variants = spread_variants(e)
    if pattern:
        hit = [v for v in variants if v[0] == pattern]
        if not hit:
            have = ' , '.join(f'{p}({n:.0f}%)' for p, _, _, n in variants)
            sys.exit(f'{name}: 配分パターン「{pattern}」は使用率データにありません。'
                     f'あるのは {have}')
        variants = hit
    p, _usage, sps, norm = variants[0]

    nature = pick_nature(e, p)
    want_mega = name in megas
    # party.txt にはメガシンカ前の実数値を書く。メガ形態を指定されていても
    # 実数値は通常形態の種族値で計算し、メガストーンを持たせて計算側に任せる。
    st = stats(DEX[base]['base'], [sps[k] for k in STAT_KEYS], nature)

    if want_mega:
        stones = [i for i in e['items'] if _is_stone(i['name'])]
        if not stones:
            sys.exit(f'{name}: メガストーンが使用率データにありません。')
        item = ITEM_JA.get(stones[0]['name'], stones[0]['name'])
    else:
        item = ITEM_JA.get(e['items'][0]['name'], e['items'][0]['name']) if e['items'] else ''

    # 特性は通常形態のものを書く。party.py は「図鑑の特性一覧に含まれるか」を見るので、
    # 通常形態に無い名前を書くと弾かれる。メガ形態の特性は計算側が差し替えるので、
    # メガを指定した場合ここに何を書いても打点には影響しない。
    #
    # M-C 以降の使用率データは特性も日本語なので、そのまま図鑑と突き合わせられる。
    # 旧データ（英語名）は対応表（generate.ABILITY_JA）を通すが、この表は
    # 「表に出る＝最も使われている特性」しか持っていない。メガ運用のポケモンは
    # 通常形態の特性が表に出ないので、対応表に無いことがある（スターミーの natural-cure）。
    # 訳せなかったときは図鑑の先頭を使い、確認できるように元の名前を注記に残す。
    ab_pool = DEX[base]['ab_list']
    ranked = sorted(e['abilities'], key=lambda x: -x['usage'])
    ability, note = '', ''
    for a in ranked:
        ja = a['name'] if a['name'] in ab_pool else ABILITY_JA.get(a['name'])
        if ja and ja in ab_pool:
            ability = ja
            break
    if not ability:
        ability = ab_pool[0] if ab_pool else ''
        top = ranked[0]['name'] if ranked else '?'
        use = f'{ranked[0]["usage"]:.0f}%' if ranked else '?'
        note = (f'# 通常形態の特性は訳せなかったので図鑑の先頭を入れた'
                f'（使用率1位は {top} {use}）。メガの特性に置き換わるので打点には影響しない\n'
                if want_mega else
                f'# ★特性を確認すること。使用率1位の {top}（{use}）が訳せず、'
                f'図鑑の先頭を入れている\n')

    moves = []
    for raw in translate_moves(e, pick_form(e), set(), set()):
        mv = raw.split(' (')[0]
        if mv in MOVES and mv not in moves:
            moves.append(mv)
        if len(moves) == 4:
            break

    label = name if want_mega else base
    stamp = e.get('season') or e.get('month') or '不明'
    # norm は Fraction（バージョン差で丸めがぶれないようにするため）。
    # Fraction を .0f で書式化できるのは Python 3.12 以降なので、先に round する
    return (f'# {label} {p}型 {round(norm)}%（{stamp} の使用率データの最頻値）\n'
            + note
            + f'{base} @ {item}\n'
            f'{NAT_JA.get(nature, nature)} / {ability}\n'
            + '-'.join(str(x) for x in st) + '\n'
            + ' / '.join(moves) + '\n')


def main():
    ap = argparse.ArgumentParser(
        description='使用率データから party.txt のブロックを起こす')
    ap.add_argument('names', nargs='+', help='ポケモン名。`名前:型` で配分を指定できる')
    args = ap.parse_args()

    out = []
    for token in args.names:
        name, _, pattern = token.partition(':')
        out.append(block(name, pattern or None))
    sys.stdout.write('\n'.join(out))


if __name__ == '__main__':
    main()
