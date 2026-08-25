#!/usr/bin/env python3
"""
相手のパーティ6体に対して、自分のどの駒が処理できるかと推奨選出を出す。

    python build/matchup.py ガブリアス ミミッキュ メガカイリュー カバルドン メガガルーラ ゲッコウガ
    python build/matchup.py --party 案A.txt --against 相手.txt

ブラウザ版は select.html（こちらが対戦中に使う本体）。このCLIは同じ判定を
チャットやスキルから使うためのもので、**判定ロジックは共有している**
（どちらも generate.process_check を呼ぶ）。片方だけ直さないこと。

型の扱いがこの機能の肝。使用率データは1体を複数の行に展開していて、行が分かれる理由は
2種類ある:
  ・配分の型（AS / HB …）… 対戦前には分からない。これが本来の「型」
  ・計算のバリアント（マルチスケイル解除後 / へんげんじざいの発動有無）… 同じ1体の別の状態
どちらも対戦中に実際に当たりうるので、**全部の行を処理できて初めて「安定」**とする。
一部だけなら「条件付き」で、どの行なら通るかも出す。
"""
import argparse
import os
import sys
import unicodedata
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate import build_threats, process_check, type_weakness, ABILITY_JA
from consult import load_members, label
from party import THREAT_RANK_LIMIT


def row_key(t):
    """行の見出し。型なのか、同じ型の別状態なのかが分かる書き方にする。"""
    k = t['pattern'] + (f"/{t['form']}" if t['form'] else '')
    if t['hp_full'] is False:
        k += '・マルチスケイル解除'
    if t['protean'] is True:
        k += '・へんげんじざい発動'
    if t['protean'] is False:
        k += '・不一致技'
    return k


def species_index(threats):
    out = {}
    for t in threats:
        out.setdefault(t['name'], []).append(t)
    return out


def fold(s):
    """照合用のキー。図鑑名はカタカナだが、変換前のひらがなで打たれても引けるように
    両側をカタカナへ寄せる。ひらがな（U+3041〜U+3096）とカタカナ（U+30A1〜U+30F6）は
    並びが同じなので 0x60 ずらすだけでよい。半角カナは NFKC で先に全角へ直す。
    select.js の fold() と同じ規則。片方だけ変えると画面とCLIで挙動が食い違う。"""
    s = unicodedata.normalize('NFKC', s or '').replace(' ', '').replace('　', '')
    return ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in s)


def strip_name(s):
    """さらに表記ゆれを落としたキー。括弧書きと「メガ」を外す。"""
    s = fold(s)
    for op, cl in (('(', ')'), ('（', '）')):
        while op in s and cl in s:
            s = s[:s.index(op)] + s[s.index(cl) + 1:]
    return s[2:] if s.startswith('メガ') else s


def resolve(name, index):
    """表記ゆれを吸収して1体に決める。決まらないときは候補を返して呼び出し側に投げる。
    前方一致を部分一致より必ず上に置く（「ガブ」で メガブリガロン が先に出ると使えない）。"""
    fq, sq = fold(name), strip_name(name)
    if not fq:
        return None, []
    ranked = []
    for n in index:
        fn, sn = fold(n), strip_name(n)
        if fn == fq:
            ranked.append((0, n))
        elif fn.startswith(fq):
            ranked.append((1, n))
        elif sn.startswith(sq):
            ranked.append((2, n))
        elif fq in fn or sq in sn:
            ranked.append((3, n))
    if not ranked:
        return None, []
    top = min(r for r, _ in ranked)
    strong = [n for r, n in ranked if r == top]
    if len(strong) == 1:
        return strong[0], []
    return None, [n for _, n in sorted(ranked)][:8]


def verdict_for(member, rows, cache):
    """(段階, 最短の技と理由, 通る行, 型比率の合計)。段階は 2=安定 1=条件付き 0=不可。"""
    ok = [t for t in rows if cache_check(member, t, cache)[0]]
    if not ok:
        return 0, None, [], 0
    best = min((cache_check(member, t, cache) for t in ok), key=lambda x: x[2])
    seen, share = set(), 0
    for t in ok:
        if t['pattern'] in seen:
            continue
        seen.add(t['pattern'])
        share += t['share']
    return (2 if len(ok) == len(rows) else 1), best, [row_key(t) for t in ok], share


def cache_check(member, threat, cache):
    """(処理できるか, 理由, ターン数)。process_check は理由の文字列にターン数が入っている
    ので、並べ替え用に手数だけ取り出しておく。"""
    key = (member['id'], threat['rank'], threat['name'], threat['pattern'],
           threat['form'], threat['hp_full'], threat['protean'])
    if key not in cache:
        ok, why = process_check(member, threat)
        turns = 1 if ('1発' in why) else int(''.join(c for c in why if c.isdigit()) or 99)
        cache[key] = (ok, why, turns)
    return cache[key]


def build_groups(members):
    """メガシンカできるのは1体だけなので、同じ枠のメガ／非メガを1つにまとめる。"""
    groups, order = {}, []
    for m in members:
        g = groups.setdefault(m['name'], {'name': m['name']})
        if g not in order:
            order.append(g)
        if m['form'] == 'メガ':
            g['mega'] = m
        elif m['form'] == '非メガ':
            g['base'] = m
        else:
            g['plain'] = m
    return order


def form_of(g, use_mega):
    return g.get('plain') or (g.get('mega') if use_mega else g.get('base'))


def recommend(groups, targets, cache):
    """3体の組み合わせを全通り試す。貪欲法にしないのは「その相手を処理できるのが
    1体だけ」という相手を取りこぼすため。枠は6つなので総当たりで足りる。"""
    size = min(3, len(groups))
    best = None
    for combo in combinations(range(len(groups)), size):
        mega_idx = [i for i in combo if groups[i].get('mega')]
        for use_mega in mega_idx + [None]:
            forms = [form_of(groups[i], i == use_mega) for i in combo]
            if any(f is None for f in forms):
                continue
            stable = partial = rows = 0
            for name, trows in targets:
                levels = [verdict_for(f, trows, cache)[0] for f in forms]
                if 2 in levels:
                    stable += 1
                elif 1 in levels:
                    partial += 1
                rows += sum(1 for f in forms for t in trows if cache_check(f, t, cache)[0])
            score = (stable, partial, rows)
            if best is None or score > best[0]:
                best = (score, combo, use_mega, forms)
    return best


def main():
    ap = argparse.ArgumentParser(description='相手6体に対する処理担当と推奨選出を出す')
    ap.add_argument('names', nargs='*', help='相手のポケモン名')
    ap.add_argument('--party', help='自分のパーティ定義（省略時は party.txt）')
    ap.add_argument('--against', help='相手の名前を1行1体で書いたファイル')
    ap.add_argument('--top', type=int, help=f'相手の順位の上限（既定は{THREAT_RANK_LIMIT}位）')
    args = ap.parse_args()

    names = list(args.names)
    if args.against:
        with open(args.against, encoding='utf-8') as f:
            names += [l.strip() for l in f if l.strip() and not l.startswith('#')]
    if not names:
        ap.error('相手の名前を指定してください')

    members = load_members(args.party)
    threats = build_threats(limit=args.top)
    index = species_index(threats)

    targets, unknown = [], []
    for n in names:
        hit, cands = resolve(n, index)
        if hit is None:
            unknown.append((n, cands))
        elif all(hit != k for k, _ in targets):
            targets.append((hit, index[hit]))

    for n, cands in unknown:
        # 黙って無視すると「見られる相手だけ数えた」結果になってしまう
        if cands:
            print(f'× {n}: 1体に決まりません。候補: {" / ".join(cands)}')
        else:
            print(f'× {n}: 使用率{max(t["rank"] for t in threats)}位までに居ないので計算できません')
    if unknown:
        print()
    if not targets:
        sys.exit('計算できる相手がありません。')

    cache = {}
    groups = build_groups(members)

    for name, rows in targets:
        t0 = rows[0]
        ab = ABILITY_JA.get(t0['ability'], t0['ability'])
        keys = ' / '.join(dict.fromkeys(
            f'{row_key(t)} {t["share"]}%' if i == 0 or t['pattern'] != rows[i - 1]['pattern']
            else row_key(t) for i, t in enumerate(rows)))
        print(f'{t0["rank"]}位 {name}（{keys}）')
        print(f'   {"/".join(x for x in t0["types"] if x)} / 特性 {ab} / {t0["item"] or "—"}'
              f' / S{t0["speed"]}{"★" if t0["scarf"] else ""}')
        x4, x2 = type_weakness(t0['types'], t0['ability'])
        weak = (f'×4 {" ".join(x4)}  ' if x4 else '') + (f'×2 {" ".join(x2)}' if x2 else '')
        print(f'   弱点: {weak or "なし"}')
        graded = []
        for g in groups:
            for use_mega in (True, False):
                f = form_of(g, use_mega)
                if f is None:
                    continue
                lvl, best, ok_keys, share = verdict_for(f, rows, cache)
                if lvl:
                    graded.append((lvl, share, f, best, ok_keys))
                if g.get('plain'):
                    break
        graded.sort(key=lambda x: (-x[0], -x[1]))
        for tag, lvl in (('安定    ', 2), ('条件付き', 1)):
            hit = [x for x in graded if x[0] == lvl]
            if not hit:
                continue
            for _l, share, f, best, ok_keys in hit:
                extra = f'  ［{" / ".join(ok_keys)} のみ・計{share}%］' if lvl == 1 else ''
                print(f'   {tag}: {label(f)}（{best[1]}）{extra}')
        if not graded:
            print('   処理不可: 対面から処理できる駒がありません')
        print()

    rec = recommend(groups, targets, cache)
    if rec:
        (stable, partial, _rows), combo, use_mega, forms = rec
        print('推奨選出: ' + ' ／ '.join(label(f) for f in forms))
        print(f'   {len(targets)}体中 {stable}体を安定して見られる'
              + (f'（条件付きを含めれば {stable + partial}体）' if partial else ''))
        if len([i for i in combo if groups[i].get('mega')]) > 1:
            who = 'どれもメガにしない' if use_mega is None else f'{groups[use_mega]["name"]} をメガにする'
            print(f'   メガストーン持ちが複数居ます。1体しかメガシンカできないので {who} 前提です')
        left = [n for n, rows in targets
                if not any(verdict_for(f, rows, cache)[0] == 2 for f in forms)]
        if left:
            print(f'   安定した回答が無い相手: {" , ".join(left)}')


if __name__ == '__main__':
    main()
