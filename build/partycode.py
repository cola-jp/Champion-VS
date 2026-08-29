#!/usr/bin/env python3
"""
パーティを1本の文字列コードにする／から戻す。

    python build/partycode.py                 # party.txt を符号化して出す
    python build/partycode.py --party 案.txt
    python build/partycode.py --decode <コード>

`party.txt` は今までどおり一次データで、これはその**持ち運び用の別表現**。
保存・受け渡しのために短くしたいだけなので、party.txt を置き換えるものではない。

## 何をしているか

パーティ全体を**1つの多倍長整数**にして、2370種類の文字で書き下す。
項目ごとに必要な通り数（基数）が違うので、ビット単位で切り上げず
`値 = 値 × 基数 + 数字` で詰める。ビット詰めより1割以上短くなる
（6体で56文字 → 46文字）。Python は標準の整数、JS は BigInt で
どちらも誤差なく同じ値になる。

## 絶対に守ること

- **ALPHABET の並びを変えない。** 変えると既存のコードが全部読めなくなる。
  変えるときは書式バージョン（VERSION）を上げて、古い版も読めるようにする。
- **data/code_dict.json は追記専用。** 名前の並びがそのままコードの意味になる。
  途中に挿入したり並べ替えたりすると、去年作ったコードが別のポケモンになる。
  新しい図鑑・技・持ち物は必ず末尾に足すこと（sync_registry がやる）。
- **JS 版（assets/partycode.js）と同時に直すこと。** 片方だけ直すと、
  ブラウザで作ったコードが Python で読めなくなる。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import ROOT, DATA, DEX, MOVES, NAT_JA, MEGA_BASE, stats
from generate import ITEM_JA, ITEM_NO_DAMAGE
from party import MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL, PartyError, _parse_party

VERSION = 1
DICT_PATH = os.path.join(DATA, 'code_dict.json')
JOYO_PATH = os.path.join(DATA, '常用漢字.txt')
# 配布物（build/make_skill.py が作る claude.ai 用のスキル）では ASCII 名で入れている。
# zip に日本語のファイル名を入れると環境によっては化けて取り出せない（実際に踏んだ）。
if not os.path.exists(JOYO_PATH):
    JOYO_PATH = os.path.join(DATA, 'joyo.txt')

MAX_PARTY = 8            # 体数の基数。party.txt 側に上限は無いが、コードはここまで
MAX_ITEM_LEN = 32        # 台帳に無い持ち物を生のまま入れるときの上限
CHECK_MOD = 4093         # 打ち間違いの検出用。4096 未満の素数


def _alphabet():
    """コードに使う文字。**この並びは凍結。** 変えると既存コードが読めなくなる。
    英数 → ひらがな → カタカナ → 常用漢字 の順で、どれも1文字が1コード単位
    （サロゲートペアが無い）ので JS 側でも1文字ずつ扱える。"""
    out = [chr(c) for c in range(0x30, 0x3A)]          # 0-9
    out += [chr(c) for c in range(0x41, 0x5B)]         # A-Z
    out += [chr(c) for c in range(0x61, 0x7B)]         # a-z
    out += [chr(c) for c in range(0x3041, 0x3097)]     # ひらがな
    out += [chr(c) for c in range(0x30A1, 0x30F7)]     # カタカナ
    with open(JOYO_PATH, encoding='utf-8') as f:
        out += [c for c in f.read() if not c.isspace()]
    if len(set(out)) != len(out):
        raise SystemExit('コードの文字集合に重複があります')
    return ''.join(out)


ALPHABET = _alphabet()
BASE = len(ALPHABET)
INDEX = {c: i for i, c in enumerate(ALPHABET)}


# ---------------------------------------------------------------- 台帳

def known_items():
    """名前が分かっている持ち物。台帳に無いものは生テキストで持つので、
    ここに載っていなくてもコードは作れる（1文字あたり16bit＝1.5字ぶん長くなるだけ）。

    メガストーンは使用率データに出てきたものしか `ITEM_JA` に無い。環境外のメガ
    （チルタリスなど）の石が抜けて生テキスト送りになり、コードが12文字も伸びていた。
    図鑑のメガ形態から「通常形態の名前＋ナイト」を作って足しておく。
    **これは符号表を埋めるための推測**で、ゲーム内の表記と違っていても実害は無い
    （その持ち物は生テキストに落ちて、少し長くなるだけ）。"""
    stones = {MEGA_BASE[m] + 'ナイト' for m in MEGA_BASE}
    return sorted(set(ITEM_JA.values()) | {x for x in ITEM_NO_DAMAGE if x} | stones)


def load_registry():
    if not os.path.exists(DICT_PATH):
        return {'version': VERSION, 'pokemon': [], 'moves': [], 'items': [], 'natures': []}
    with open(DICT_PATH, encoding='utf-8') as f:
        return json.load(f)


def sync_registry(write=True):
    """図鑑・技・持ち物・性格を台帳に取り込む。**末尾に足すだけで並べ替えない。**
    追記した名前を返す。ここで並びが動くと、過去のコードの意味が変わる。"""
    reg = load_registry()
    added = {}
    for key, names in (('pokemon', sorted(DEX)), ('moves', sorted(MOVES)),
                       ('items', known_items()), ('natures', sorted(NAT_JA.values()))):
        have = set(reg.get(key) or [])
        new = [n for n in names if n not in have]
        if new:
            reg.setdefault(key, []).extend(new)
            added[key] = new
    if added and write:
        with open(DICT_PATH, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(reg, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write('\n')
    return reg, added


REG, _ADDED = sync_registry(write=False)
P_LIST, M_LIST = REG['pokemon'], REG['moves']
I_LIST, N_LIST = REG['items'], REG['natures']
P_IDX = {n: i for i, n in enumerate(P_LIST)}
M_IDX = {n: i for i, n in enumerate(M_LIST)}
I_IDX = {n: i for i, n in enumerate(I_LIST)}
N_IDX = {n: i for i, n in enumerate(N_LIST)}


# ---------------------------------------------------------------- 能力ポイント

def ev_table():
    """EV_COUNT[k][rem] = 残り k ステータスを、合計 rem 以下で埋める場合の数。
    1ステータス最大 MAX_POINTS_PER_STAT。この表で通し番号との相互変換をする。
    **JS には表そのものを渡す。** 同じ漸化式を2箇所に書くと必ずずれる。"""
    top = MAX_POINTS_TOTAL
    table = [[1] * (top + 1)]
    for k in range(1, 7):
        prev, row = table[k - 1], []
        for rem in range(top + 1):
            row.append(sum(prev[rem - v] for v in range(0, min(MAX_POINTS_PER_STAT, rem) + 1)))
        table.append(row)
    return table


EV_COUNT = ev_table()
EV_TOTAL = EV_COUNT[6][MAX_POINTS_TOTAL]


def ev_rank(ev):
    """能力ポイント6つを 0〜EV_TOTAL-1 の通し番号にする。"""
    r, rem = 0, MAX_POINTS_TOTAL
    for i, v in enumerate(ev):
        if not 0 <= v <= MAX_POINTS_PER_STAT:
            raise PartyError(f'能力ポイントが範囲外です: {ev}')
        if v > rem:
            raise PartyError(f'能力ポイントの合計が{MAX_POINTS_TOTAL}を超えています: {ev}')
        k = 5 - i
        for x in range(v):
            r += EV_COUNT[k][rem - x]
        rem -= v
    return r


def ev_unrank(r):
    ev, rem = [], MAX_POINTS_TOTAL
    for i in range(6):
        k = 5 - i
        for x in range(0, min(MAX_POINTS_PER_STAT, rem) + 1):
            c = EV_COUNT[k][rem - x]
            if r < c:
                ev.append(x)
                rem -= x
                break
            r -= c
        else:
            raise PartyError('コードの能力ポイントが読めません')
    return ev


# ---------------------------------------------------------------- 桁の組み立て

def _pack(pairs):
    """(基数, 数字) を**読み出す順**に並べたものを1つの整数にする。
    先頭が最下位になるように、後ろから詰める。"""
    v = 0
    for radix, digit in reversed(pairs):
        if not 0 <= digit < radix:
            raise PartyError(f'コードに入らない値です: {digit} (基数{radix})')
        v = v * radix + digit
    return v


class _Reader:
    def __init__(self, value):
        self.v = value

    def take(self, radix):
        d = self.v % radix
        self.v //= radix
        return d


def to_text(value):
    if value == 0:
        return ALPHABET[0]
    out = []
    while value:
        value, d = divmod(value, BASE)
        out.append(ALPHABET[d])
    return ''.join(reversed(out))


def from_text(text):
    v = 0
    for ch in text:
        if ch.isspace():
            continue
        if ch not in INDEX:
            raise PartyError(f'コードに使えない文字が入っています: {ch!r}')
        v = v * BASE + INDEX[ch]
    return v


# ---------------------------------------------------------------- 符号化

def _mon_pairs(p):
    """1体ぶんの (基数, 数字) を読み出し順に並べる。"""
    sp = p['name']          # party.txt に書く通常形態の名前
    if sp not in P_IDX:
        raise PartyError(f'台帳に無いポケモンです: {sp}')
    ab_list = DEX[sp]['ab_list'] or ['']
    if p['ability'] not in ab_list:
        raise PartyError(f'{sp} の特性ではありません: {p["ability"]}')
    nat = NAT_JA.get(p['nature'], p['nature'])
    if nat not in N_IDX:
        raise PartyError(f'台帳に無い性格です: {nat}')

    pairs = [(len(P_LIST), P_IDX[sp]),
             (len(N_LIST), N_IDX[nat]),
             # 特性は「その種が持つ数」を基数にする。1つしか無い種は0桁で済む
             (len(ab_list), ab_list.index(p['ability'])),
             (len(I_LIST) + 1, I_IDX.get(p['item'], len(I_LIST)))]
    if p['item'] not in I_IDX:
        # 台帳に無い持ち物は生のまま入れる。長くなるが、名前を失うよりよい
        if len(p['item']) > MAX_ITEM_LEN:
            raise PartyError(f'持ち物の名前が長すぎます: {p["item"]}')
        pairs.append((MAX_ITEM_LEN + 1, len(p['item'])))
        pairs += [(0x10000, ord(c)) for c in p['item']]
    pairs.append((EV_TOTAL, ev_rank(p['ev'])))
    moves = p['moves']
    if not 1 <= len(moves) <= 4:
        raise PartyError(f'技は1〜4個にしてください: {moves}')
    pairs.append((4, len(moves) - 1))
    for mv in moves:
        if mv not in M_IDX:
            raise PartyError(f'台帳に無い技です: {mv}')
        pairs.append((len(M_LIST), M_IDX[mv]))
    return pairs


def collapse(party):
    """`_parse_party` はメガストーン持ちを「メガ」「非メガ」の2件に展開する。
    party.txt に書いてあるのは1件なので、符号化する前に元の形に戻す。

    **通常形態の名前と特性は非メガ側、メガストーンはメガ側**に入っている。
    非メガ側の持ち物は `—` になっているので、そのまま使うと石が消える（実際に消した）。"""
    groups = {}
    for p in party:
        groups.setdefault(p['id'].split('_')[0], []).append(p)
    out = []
    for key in sorted(groups):
        group = groups[key]
        base = next((g for g in group if g['form'] != 'メガ'), group[0])
        mega = next((g for g in group if g['form'] == 'メガ'), None)
        out.append(dict(base, item=mega['item'] if mega else base['item']))
    return out


def encode(party):
    """party.py の PARTY 相当を文字列コードにする。"""
    mons = collapse(party)
    if not 1 <= len(mons) <= MAX_PARTY:
        raise PartyError(f'コードにできるのは1〜{MAX_PARTY}体です')
    pairs = [(MAX_PARTY + 1, len(mons))]
    for p in mons:
        pairs += _mon_pairs(p)
    body = _pack(pairs)
    value = (body * CHECK_MOD + body % CHECK_MOD) * 16 + VERSION
    return to_text(value)


def decode(text):
    """コードを party.txt のテキストに戻す。"""
    value = from_text(text)
    ver = value % 16
    value //= 16
    if ver != VERSION:
        # 1文字違うだけでもここに落ちることが多い。「新しい書式」と決めつけない
        raise PartyError(f'コードが読めません（打ち間違いか、知らない書式です。'
                         f'読み取った書式番号 {ver}、この版は {VERSION}）')
    check = value % CHECK_MOD
    body = value // CHECK_MOD
    if body % CHECK_MOD != check:
        raise PartyError('コードが壊れています（打ち間違いの可能性があります）')

    r = _Reader(body)
    count = r.take(MAX_PARTY + 1)
    if not 1 <= count <= MAX_PARTY:
        raise PartyError('コードの体数が読めません')
    blocks = []
    for _ in range(count):
        sp = P_LIST[_check_idx(r.take(len(P_LIST)), P_LIST, 'ポケモン')]
        nat = N_LIST[_check_idx(r.take(len(N_LIST)), N_LIST, '性格')]
        ab_list = DEX[sp]['ab_list'] or ['']
        ability = ab_list[r.take(len(ab_list))]
        ii = r.take(len(I_LIST) + 1)
        if ii < len(I_LIST):
            item = I_LIST[ii]
        else:
            n = r.take(MAX_ITEM_LEN + 1)
            item = ''.join(chr(r.take(0x10000)) for _ in range(n))
        ev = ev_unrank(r.take(EV_TOTAL))
        nmv = r.take(4) + 1
        moves = [M_LIST[_check_idx(r.take(len(M_LIST)), M_LIST, '技')] for _ in range(nmv)]
        st = stats(DEX[sp]['base'], ev, NAT_JA_TO_EN[nat])
        blocks.append(f'{sp} @ {item}\n{nat} / {ability}\n'
                      + '-'.join(str(x) for x in st) + '\n' + ' / '.join(moves))
    if r.v:
        raise PartyError('コードに余分な情報が付いています')
    return '\n\n'.join(blocks) + '\n'


NAT_JA_TO_EN = {v: k for k, v in NAT_JA.items()}


def _check_idx(i, lst, what):
    if i >= len(lst):
        raise PartyError(f'この版では読めない{what}が入っています'
                         f'（新しいデータで作られたコードかもしれません）')
    return i


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description='パーティを文字列コードにする／から戻す')
    ap.add_argument('--party', help='符号化する party.txt（省略時はリポジトリのもの）')
    ap.add_argument('--decode', help='コードを party.txt に戻す')
    args = ap.parse_args()

    if args.decode:
        sys.stdout.write(decode(args.decode))
        return
    path = args.party or os.path.join(ROOT, 'party.txt')
    with open(path, encoding='utf-8') as f:
        party = _parse_party(f.read())
    code = encode(party)
    print(code)
    print(f'  {len(code)} 文字 / 文字集合 {BASE} 種類', file=sys.stderr)


if __name__ == '__main__':
    main()
