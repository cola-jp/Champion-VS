#!/usr/bin/env python3
"""
構築相談用の「相談パック」を1枚のMarkdownで書き出す。

    python build/consult.py                      # party.txt のパーティで標準出力へ
    python build/consult.py -o consult.md        # ファイルに書く
    python build/consult.py --party 案A.txt      # 別のパーティ案で
    python build/consult.py --top 30             # 相手を上位30位に絞る
    python build/consult.py --candidates         # 空き枠に入れる候補を出す（軸だけのときに使う）

パーティは6体揃っていなくてよい。軸だけ2体書いたファイルを渡せば、その2体で
環境のどこが見られてどこが見られないかが出る。`build/seed_party.py` を使えば
使用率データから軸のブロックを起こせるので、育てていないポケモンでも試せる。

index.html は「対面したこの1体に何を撃つか」を出す道具なので、構築相談には向かない。
相談で要るのは「環境全体に対してどこで詰むか」という集計で、必要な切り口が違う。
そこで表と同じエンジン（generate.my_hit / their_hit）を使い、出力だけを変える。
数字の出どころは表と完全に同じなので、片方だけ古くなることは無い。

出したMarkdownはそのままチャットに貼れる。ダメージ計算はここで済ませてあるので、
読み手（人でもClaudeでも）は計算をやり直す必要がなく、解釈と提案だけをすればよい。
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import (MOVES, USAGE, BY_DEX_NO, NAT_JA, verdict, VERDICT_RANK, is_mega)
import party as party_mod
from generate import (build_threats, build_members, my_hit, their_hit, choose_move,
                      ABILITY_JA)
from party import THREAT_RANK_LIMIT

# 「落とせる」と見なす判定。乱1は乱数なので確実ではないが、選出の判断材料としては同格に扱う。
KO_VERDICTS = ('確1', '乱1')


def data_month():
    months = {e.get('month') for e in USAGE if e.get('month')}
    return sorted(months)[-1] if months else '不明'


def label(member):
    return member['name'] + (f"({member['form']})" if member['form'] else '')


def threat_label(t):
    return t['name'] + (f"({t['form']})" if t['form'] else '')


def load_members(path):
    """--party で渡されたファイルからメンバーを作る。省略時は party.txt。"""
    if not path:
        return build_members()
    with open(path, encoding='utf-8') as f:
        text = f.read()
    try:
        return build_members(party_mod._parse_party(text))
    except party_mod.PartyError as e:
        # 書式エラーの本文は「party.txt N体目」と書かれているので、
        # どのファイルを読んでいたのかを添えないと別案を検討中に混乱する。
        sys.exit(f'{path} の読み込みに失敗しました:\n  {e}')


def cell(member, threat):
    """1マスぶんの計算結果。表と同じ関数を通す。"""
    hits = [my_hit(member, mv, threat) for mv in member['moves']]
    primary, _ = choose_move(hits)
    ohko = next((h for h in hits if h and h.get('ohko')), None)
    back = their_hit(threat, member)
    hp = member['st'][0]
    back_v = verdict(back['lo'], back['hi'], hp) if back['move'] != '—' else '—'
    return dict(
        move=primary['move'] if primary else '—',
        verdict=primary['verdict'] if primary else '—',
        ph=primary['ph'] if primary else 0,
        ohko=ohko['move'] if ohko else None,
        back_move=back['move'], back_ph=back['ph'], back_verdict=back_v,
        faster=member['speed'] > threat['speed'],
    )


def build_matrix(members, threats):
    return [[cell(m, t) for m in members] for t in threats]


# ---------------------------------------------------------------- 各節

def sec_intro(threats, month):
    ranks = max(t['rank'] for t in threats)
    return f"""# 構築相談パック（ポケモンチャンピオンズ / レギュレーションM-B シングル）

対面ダメージ表 Champion-VS が計算した結果を、構築相談用に集計したもの。
ダメージは計算済みなので、読み手は計算をやり直さなくてよい。

- 使用率データ: **{month}** 時点（使用率上位{ranks}位まで、型違いを展開して{len(threats)}行）
- 「#」は使用率順位。「型比率」はそのポケモンの中でその配分型が占める割合で、環境全体の使用率ではない
- レベル50固定・個体値31・ステルスロック無しの1対1で計算している
- 判定: `確1`=確定1発 / `乱1`=乱数1発 / `確2` / `乱2` / `確3` / `4発+`
- 与ダメージは自分の技のうち**最も判定の良い技**、被ダメージは相手の**採用率10%超の技での最大打点**
- 素早さは実数値の比較のみ（こだわりスカーフは反映済み、ランク変化・天候は未反映）
- メガシンカする駒は「メガ」「非メガ」を別の行として出している

考慮していないもの: 状態異常、天候・フィールド、急所、みがわり、交代読み、複数回行動。
**対面1回の殴り合いだけ**を見た数字であることに注意。
"""


def sec_party(members):
    out = ['## このパーティ', '',
           '| 駒 | 持ち物 | 性格 | 特性 | H-A-B-C-D-S | 技 |',
           '|---|---|---|---|---|---|']
    for m in members:
        st = '-'.join(str(x) for x in m['st'])
        ab = ABILITY_JA.get(m.get('ability'), m.get('ability')) or '—'
        nat = NAT_JA.get(m['nature'], m['nature'])
        out.append(f"| {label(m)} | {m.get('item') or '—'} | {nat} | {ab} | "
                   f"{st} | {' / '.join(m['moves'])} |")
    return '\n'.join(out) + '\n'


def sec_scoreboard(members, threats, matrix):
    """駒ごとの成績。どの枠を差し替えるか考えるときはここを最初に見る。"""
    total = len(threats)
    out = ['## 駒ごとの成績', '',
           'その駒だけを出したと仮定して、環境の各行にどう当たるかを数えたもの。',
           '「仕事あり」は「1発で落とせて、かつ相手からは1発で落ちない」行の数で、',
           '対面から役割を持てる相手がどれだけ居るかの目安。', '',
           '| 駒 | 落とせる | 1発で落ちる | 素早さ勝ち | 仕事あり |',
           '|---|---|---|---|---|']
    for i, m in enumerate(members):
        ko = sum(1 for r in matrix if r[i]['verdict'] in KO_VERDICTS)
        died = sum(1 for r in matrix if r[i]['back_verdict'] == '確1')
        fast = sum(1 for r in matrix if r[i]['faster'])
        role = sum(1 for r in matrix
                   if r[i]['verdict'] in KO_VERDICTS and r[i]['back_verdict'] != '確1')
        out.append(f"| {label(m)} | {ko}/{total} | {died}/{total} | "
                   f"{fast}/{total} | {role}/{total} |")
    return '\n'.join(out) + '\n'


def answers(c):
    """その1マスで「対面から仕事ができる」か。
    1発で落とせて、かつ1発では落とされないか、落とされるとしても先に動ける。"""
    return (c['verdict'] in KO_VERDICTS
            and (c['back_verdict'] not in ('確1', '乱1') or c['faster']))


def hard_threats(members, threats, matrix):
    """重い相手。対面から仕事ができる駒が1つも無い行を拾う。"""
    rows = []
    for t, row in zip(threats, matrix):
        ko = [i for i, c in enumerate(row) if c['verdict'] in KO_VERDICTS]
        if not any(answers(c) for c in row):
            rows.append((t, row, ko))
    return rows


def sec_hard(members, threats, matrix):
    rows = hard_threats(members, threats, matrix)
    out = ['## 重い相手', '',
           '「1発で落とせて、かつ相手より先に動けるか1発では落ちない」駒が1つも無い行。',
           'ここに並ぶ相手が、選出で毎回困る相手になる。', '']
    if not rows:
        out.append('該当なし。どの行にも対面から仕事ができる駒がある。')
        return '\n'.join(out) + '\n'
    for t, row, ko in rows:
        ab = ABILITY_JA.get(t['ability'], t['ability'])
        typ = '/'.join(x for x in t['types'] if x)
        out.append(f"### {t['rank']}位 {threat_label(t)} "
                   f"{t['pattern']}（この型の割合{t['share']}%）")
        out.append('')
        out.append(f"- {typ} / 特性 {ab} / 持ち物 {t['item']} / {t['nature']} / "
                   f"H-A-B-C-D-S {'-'.join(str(x) for x in t['st'])} / S実数値 {t['speed']}")
        out.append('- 技（採用率）: '
                   + ' , '.join(f'{mv} {u:.0f}%' for mv, u in t['moves_use'][:6]))
        best = max(range(len(members)),
                   key=lambda i: (VERDICT_RANK.get(row[i]['verdict'], 0), row[i]['ph']))
        b = row[best]
        out.append(f"- こちらの最大打点: {label(members[best])} の {b['move']} "
                   f"で {b['ph']}%（{b['verdict']}）")
        worst = max(range(len(members)), key=lambda i: row[i]['back_ph'])
        w = row[worst]
        out.append(f"- 相手の最大打点: {w['back_move']} が "
                   f"{label(members[worst])} に {w['back_ph']}%")
        if ko:
            out.append('- 1発で落とせる駒: ' + ' , '.join(label(members[i]) for i in ko)
                       + '（ただしいずれも先に動かれて落とされる）')
        else:
            out.append('- 1発で落とせる駒: なし')
        out.append('')
    return '\n'.join(out) + '\n'


def env_candidates(threats):
    """環境上位の型を、そのまま「味方に入れたらどうなるか」を試せるメンバーにする。

    候補を図鑑から総当たりしないのは、配分と技構成を仮定しないと計算できないから。
    使用率データに入っている型は実際に使われている調整なので、仮定を持ち込まずに済む。
    そのぶん候補は環境上位に限られる（圏外のポケモンを試したいときは
    party.txt の書式で書いて --party に渡す）。

    マルチスケイルやへんげんじざいの2行分割は同じ1体なので、
    （名前, 配分パターン）で重複を除く。"""
    out, seen = [], set()
    for t in threats:
        key = (t['name'], t['pattern'])
        if key in seen:
            continue
        seen.add(key)
        ab = ABILITY_JA.get(t['ability'], t['ability']) or ''
        moves = []
        for mv, _u in t['moves_use']:
            if mv in MOVES and mv not in moves:
                moves.append(mv)
            if len(moves) == 4:
                break
        m = party_mod._make_member(
            f"env{t['rank']}_{t['pattern']}", t['name'], t['form'], t['name'],
            [0] * 6, 'hardy', ab, t['item'], moves, t['scarf'])
        # 実数値・タイプ・素早さは使用率データ側で計算済みのものを使う。
        # ev と nature を持たせていないのはそのため（逆算はしない）。
        m['st'], m['types'], m['speed'] = t['st'], t['types'], t['speed']
        # _ability_flags は完全一致なので、メガ形態のように特性名が図鑑の連結文字列
        # （複数特性がつながったもの）だと外れる。打点に効くかたやぶりだけ入れ直す。
        m['mold_breaker'] = any(k in ab for k in
                                ('かたやぶり', 'ターボブレイズ', 'テラボルテージ'))
        m['rank'], m['pattern'], m['share'] = t['rank'], t['pattern'], t['share']
        out.append(m)
    return out


def sec_candidates(members, threats, matrix, limit=15):
    """空き枠の候補。いま重い相手を、環境のどの型なら見られるかで並べる。"""
    hard = hard_threats(members, threats, matrix)
    out = ['## 空き枠の候補', '']
    if not hard:
        out.append('重い相手が無いので、この節で並べるものがない。')
        return '\n'.join(out) + '\n'

    have = {m['name'].replace('メガ', '', 1) if is_mega(m['name']) else m['name']
            for m in members}
    hard_ts = [t for t, _row, _ko in hard]

    scored = []
    for cand in env_candidates(threats):
        base = cand['name'].replace('メガ', '', 1) if is_mega(cand['name']) else cand['name']
        if base in have:
            continue        # すでに入っている枠を候補に出しても意味がない
        solved = [t for t in hard_ts if answers(cell(cand, t))]
        if not solved:
            continue
        role = sum(1 for t in threats if answers(cell(cand, t)))
        scored.append((len(solved), role, cand, solved))
    scored.sort(key=lambda x: (-x[0], -x[1]))

    out += [
        f'いま重い相手が{len(hard)}行ある。それを「対面から見られる」型を、',
        '使用率データに入っている環境上位の型の中から探して並べたもの。',
        '',
        '**この並びは対面性能だけで付けている。** 役割の重複、並びとしての相性、',
        '積みの通し方、天候やサポートは見ていないので、候補の絞り込みにだけ使うこと。',
        '「仕事あり」はその候補が環境全体（' + str(len(threats)) + '行）で',
        '対面から仕事ができる行の数で、器用さの目安。',
        '',
        f'| 候補 | 重い相手を何行見られるか | 仕事あり | 見られる相手 |',
        '|---|---|---|---|']
    for n, role, cand, solved in scored[:limit]:
        names = ' , '.join(f'{threat_label(t)}{t["pattern"]}' for t in solved[:5])
        if len(solved) > 5:
            names += f' ほか{len(solved) - 5}'
        out.append(f"| {label(cand)} {cand['pattern']} | {n}/{len(hard)} | "
                   f"{role}/{len(threats)} | {names} |")
    if not scored:
        out.append('| — | 0 | — | 環境上位の型では見られる相手が見つからなかった |')
    out.append('')
    out.append('候補の詳しい型（実数値・技）は「対面表」の相手側の行と同じ。'
               '試すときは `python build/seed_party.py <名前>` でブロックを起こして'
               'パーティに足し、`--party` で回し直す。')
    return '\n'.join(out) + '\n'


def sec_matrix(members, threats, matrix):
    head = ' | '.join(label(m) for m in members)
    sep = '|'.join(['---'] * (len(members) + 3))
    out = ['## 対面表', '',
           'セルの読み方: `与判定/被最大% 素早さ`。`>` は自分が速い、`<` は相手が速い。',
           '`!` はその駒が一撃必殺技を持っている（命中は別途）。', '',
           f'| # | 相手 | 型比率 | {head} |',
           f'|{sep}|']
    for t, row in zip(threats, matrix):
        cells = []
        for c in row:
            mark = '>' if c['faster'] else '<'
            bang = '!' if c['ohko'] else ''
            cells.append(f"{c['verdict']}/{c['back_ph']}{mark}{bang}")
        out.append(f"| {t['rank']} | {threat_label(t)} {t['pattern']} | {t['share']}% | "
                   + ' | '.join(cells) + ' |')
    return '\n'.join(out) + '\n'


def sec_speed(members, threats):
    """素早さライン。抜き調整を考えるときに使う。"""
    lines = sorted({t['speed'] for t in threats}, reverse=True)
    out = ['## 素早さ', '',
           '環境の素早さ実数値と、そこを抜いている駒。こだわりスカーフは反映済み。', '',
           '| 実数値 | 相手 | ここを抜いている駒 |', '|---|---|---|']
    for s in lines:
        who = sorted({threat_label(t) for t in threats if t['speed'] == s})
        mine = [label(m) for m in members if m['speed'] > s]
        tail = ' ほか' if len(who) > 4 else ''
        out.append(f"| {s} | {' , '.join(who[:4])}{tail} | "
                   f"{' , '.join(mine) if mine else '—'} |")
    out.append('')
    out.append('自分の素早さ: ' + ' , '.join(f'{label(m)} {m["speed"]}' for m in members))
    return '\n'.join(out) + '\n'


def sec_environment(threats):
    """環境の分布。どのタイプに厚くするかを決める材料。

    重みは「1体を1.0として、型比率で按分した数」。share は環境全体の使用率ではなく
    そのポケモンの中での型の割合なので、そのまま足すと型が1つに寄っているポケモンだけ
    重く数えてしまう。使用率データに全体の使用率%は入っていないので、上位N体を
    等しく1体と数えるのが今出せる一番まともな重み付けになる。

    マルチスケイルやへんげんじざいで2行に分かれている型は同じ1体なので、
    （名前, 配分パターン）で重複を除く。除かないと該当のポケモンだけ倍に数えてしまう。
    合計が上位N体に足りないのは、使用率データの spreads が上位12件しか無く、
    さらに10%未満の型を落としているため（元データの打ち切り）。"""
    types, items = Counter(), Counter()
    seen, rows = set(), []
    for t in threats:
        key = (t['name'], t['pattern'])
        if key in seen:
            continue
        seen.add(key)
        rows.append(t)
    for t in rows:
        w = t['share'] / 100
        for x in t['types']:
            if x:
                types[x] += w
        items[t['item']] += w
    total = sum(t['share'] / 100 for t in rows)
    ranks = len({t['rank'] for t in rows})
    out = ['## 環境の分布', '',
           f'上位{ranks}体を「1体＝1.0、型比率で按分」で数えた分布（拾えたのは {total:.0f} 体ぶん。',
           '残りは元データが上位12配分しか持っていないぶんの取りこぼし）。',
           '複合タイプは両方に1.0ずつ加算しているので、タイプの合計は体数を超える。', '',
           '| タイプ | 体数 |', '|---|---|']
    for name, w in types.most_common():
        out.append(f'| {name} | {w:.1f} |')
    out.append('')
    out.append('よく使われている持ち物: '
               + ' , '.join(f'{n} {w:.1f}' for n, w in items.most_common(8)))
    return '\n'.join(out) + '\n'


def sec_teammates(threats):
    """使用率データに入っている「同時採用されやすいポケモン」。
    構築の相方を考えるときの材料。ダメージ計算とは無関係な生データ。"""
    agg = Counter()
    ranks = {t['rank'] for t in threats}
    seen = 0
    for e in USAGE:
        if e['pick_rank'] not in ranks:
            continue
        seen += 1
        for tm in e.get('teammates') or []:
            names = BY_DEX_NO.get(tm['pokemon_id']) or []
            base = next((n for n in names if not is_mega(n)), names[0] if names else None)
            if base:
                agg[base] += tm['usage']
    if not agg or not seen:
        return ''
    out = ['## 環境で同時採用されやすいポケモン', '',
           f'使用率データの teammates（そのポケモンを使った構築に同居した割合）を、',
           f'上位{seen}体ぶん平均したもの。相方として何が組まれているか、',
           'つまりどの並びを想定すべきかの材料になる。',
           'teammates は各ポケモン上位10件しか入っていないので、実際の値より低めに出る。', '',
           '| ポケモン | 平均同居率 |', '|---|---|']
    for name, w in agg.most_common(20):
        out.append(f'| {name} | {w / seen:.1f}% |')
    return '\n'.join(out) + '\n'


def sec_howto():
    return """## 相談のしかた

このファイルを読んだうえで、例えばこう聞ける。

- 「重い相手」に並んでいる相手を、いま入っている駒の技構成を変えるだけで見られないか
- ○枠目を別のポケモンに替えるなら候補は何か。替えたら重い相手はどう変わるか
- 素早さをあと何ポイント振れば、どの相手を抜けるか

新しい案を数字で確かめたいときは、案を party.txt の書式で書いて
`python build/consult.py --party 案.txt` を実行すれば、同じ集計が案のぶんだけ出る。
party.txt の書式はそのファイル冒頭のコメントに書いてある。
"""


def main():
    ap = argparse.ArgumentParser(description='構築相談用のMarkdownを書き出す')
    ap.add_argument('-o', '--out', help='書き出し先。省略すると標準出力')
    ap.add_argument('--party', help='party.txt 以外のパーティ定義ファイル')
    ap.add_argument('--top', type=int,
                    help=f'相手を上位N位に絞る（既定は{THREAT_RANK_LIMIT}位まで全部）')
    ap.add_argument('--candidates', action='store_true',
                    help='重い相手を見られる型を環境上位から探して並べる（軸だけのときに使う）')
    args = ap.parse_args()

    members = load_members(args.party)
    threats = build_threats()
    if args.top:
        threats = [t for t in threats if t['rank'] <= args.top]
    matrix = build_matrix(members, threats)

    doc = '\n'.join([
        sec_intro(threats, data_month()),
        sec_party(members),
        sec_scoreboard(members, threats, matrix),
        sec_hard(members, threats, matrix),
        sec_candidates(members, threats, matrix) if args.candidates else '',
        sec_matrix(members, threats, matrix),
        sec_speed(members, threats),
        sec_environment(threats),
        sec_teammates(threats),
        sec_howto(),
    ])

    if args.out:
        with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(doc)
        size = len(doc.encode('utf-8')) / 1024
        print(f'書き出し完了: {args.out}  ({size:.1f} KB)')
    else:
        sys.stdout.write(doc)


if __name__ == '__main__':
    main()
