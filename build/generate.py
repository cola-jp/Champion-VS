#!/usr/bin/env python3
"""
対面ダメージ表 index.html を生成する。

    python build/generate.py

data/ 配下のデータと build/party.py のパーティ定義を読み、リポジトリ直下に index.html を書き出す。
生成物は編集しないこと。中身を変えたいときは party.py かこのスクリプトを直す。
"""
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import (ROOT, DEX, MOVES, USAGE, BY_DEX_NO, NAT_JA, resolve_form,
                    MOVE_NAME_EN_JA, LEGACY_USE, fix_move_name,
                    PokemonNotFoundError, RegionFormError,
                    stats, eff, ability_mod, damage, verdict, VERDICT_RANK, SOUND)
from party import (PARTY, DRAWBACK_MOVES, SLASH_MOVES, OHKO_MOVES, STATUS_MOVES,
                   THREAT_RANK_LIMIT, SPREAD_THRESHOLD)

STAT_KEYS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']
STAT_LETTERS = ['H', 'A', 'B', 'C', 'D', 'S']
NATURE_BOOSTS = {'lonely': 'A', 'brave': 'A', 'adamant': 'A', 'naughty': 'A',
                 'bold': 'B', 'relaxed': 'B', 'impish': 'B', 'lax': 'B',
                 'timid': 'S', 'hasty': 'S', 'jolly': 'S', 'naive': 'S',
                 'modest': 'C', 'mild': 'C', 'quiet': 'C', 'rash': 'C',
                 'calm': 'D', 'gentle': 'D', 'sassy': 'D', 'careful': 'D'}

TYPE_COLOR = {'ノーマル': '#a8a878', 'ほのお': '#f08030', 'みず': '#6890f0', 'でんき': '#f8d030',
              'くさ': '#78c850', 'こおり': '#98d8d8', 'かくとう': '#c03028', 'どく': '#a040a0',
              'じめん': '#e0c068', 'ひこう': '#a890f0', 'エスパー': '#f85888', 'むし': '#a8b820',
              'いわ': '#b8a038', 'ゴースト': '#705898', 'ドラゴン': '#7038f8', 'あく': '#8a6e5a',
              'はがね': '#b8b8d0', 'フェアリー': '#ee99ac'}
VERDICT_CLASS = {'確1': ('v1', 'var(--ko)'), '乱1': ('v2', 'var(--rng)'),
                 '確2': ('v3', 'var(--mid)'), '乱2': ('v4', 'var(--mid)'),
                 '確3': ('v5', 'var(--weak)'), '4発+': ('v6', 'var(--weak)')}

ABILITY_JA = {
    'adaptability': 'てきおうりょく', 'disguise': 'ばけのかわ', 'drizzle': 'あめふらし',
    'electromorphosis': 'でんきにかえる', 'flame-body': 'ほのおのからだ',
    'good-as-gold': 'おうごんのからだ', 'infiltrator': 'すりぬけ', 'inner-focus': 'せいしんりょく',
    'levitate': 'ふゆう', 'mold-breaker': 'かたやぶり', 'multiscale': 'マルチスケイル',
    'prankster': 'いたずらごころ', 'pressure': 'プレッシャー', 'protean': 'へんげんじざい',
    'rough-skin': 'さめはだ', 'sand-stream': 'すなおこし', 'sharpness': 'きれあじ',
    'snow-warning': 'ゆきふらし', 'stamina': 'じきゅうりょく', 'stance-change': 'バトルスイッチ',
    'supreme-overlord': 'そうだいしょう', 'torrent': 'げきりゅう', 'toxic-debris': 'どくげしょう',
    'unaware': 'てんねん', 'weak-armor': 'くだけるよろい',
}
ITEM_JA = {
    'black-glasses': 'くろいメガネ', 'choice-scarf': 'こだわりスカーフ', 'damp-rock': 'しめったいわ',
    'focus-sash': 'きあいのタスキ', 'leftovers': 'たべのこし', 'life-orb': 'いのちのたま',
    'light-clay': 'ひかりのねんど', 'sitrus-berry': 'オボンのみ', 'lum-berry': 'ラムのみ',
    'blazikenite': 'バシャーモナイト', 'charizardite-y': 'リザードナイトY', 'clefablite': 'ピクシーナイト',
    'delphoxite': 'マフォクシーナイト', 'dragonitite': 'カイリューナイト', 'gengarite': 'ゲンガナイト',
    'greninjite': 'ゲッコウガナイト', 'gyaradosite': 'ギャラドスナイト', 'lopunnite': 'ミミロップナイト',
    'lucarionite': 'ルカリオナイト', 'mawilite': 'クチートナイト', 'meganiumite': 'メガニウムナイト',
    'metagrossite': 'メタグロスナイト', 'raichunite-y': 'ライチュウナイトY', 'scizorite': 'ハッサムナイト',
    'staraptorite': 'ムクホークナイト', 'starmienite': 'スターミーナイト', 'swampertite': 'ラグラージナイト',
    'venusaurite': 'フシギバナイト',
}
MULTI_HIT = {'スケイルショット': '2〜5回', 'トリプルアクセル': '3回', 'ロックブラスト': '2〜5回',
             'タネマシンガン': '2〜5回', 'ミサイルばり': '2〜5回', 'つららばり': '2〜5回',
             'ダブルウイング': '2回'}


# ---------------------------------------------------------------- 相手の型を作る

def spread_pattern(sps):
    """投資量の多い上位2ステータスを H,A,B,C,D,S の正順で表記する。
    CSとSCのような順序違いを同一視し、第3ステータスへの端数振りは無視する。"""
    invested = sorted([(STAT_LETTERS[i], sps[STAT_KEYS[i]]) for i in range(6)
                       if sps[STAT_KEYS[i]] >= 8], key=lambda x: -x[1])[:2]
    order = {l: i for i, l in enumerate(STAT_LETTERS)}
    return ''.join(x[0] for x in sorted(invested, key=lambda x: order[x[0]])) or '無振り'


def spread_variants(entry):
    """採用率SPREAD_THRESHOLD%以上のパターンを最大2件返す。
    JSONのspreadsは各ポケモン上位12件しか無く合計は平均71.5%にしかならないので、
    表示用の比率は報告分の合計で割り直す。"""
    total = sum(s['usage'] for s in entry['spreads'])
    agg = {}
    for s in entry['spreads']:
        p = spread_pattern(s['sps'])
        a = agg.setdefault(p, {'usage': 0.0, 'best': None, 'best_usage': 0.0})
        a['usage'] += s['usage']
        if s['usage'] > a['best_usage']:
            a['best_usage'] = s['usage']
            a['best'] = s['sps']
    out = [(p, d['usage'], d['best'], d['usage'] / total * 100)
           for p, d in agg.items() if d['usage'] >= SPREAD_THRESHOLD]
    if not out:
        p, d = max(agg.items(), key=lambda x: x[1]['usage'])
        out = [(p, d['usage'], d['best'], d['usage'] / total * 100)]
    out.sort(key=lambda x: -x[1])
    return out[:2]


def pick_nature(entry, pattern):
    """その配分パターンで上がるステータスを伸ばす性格のうち最頻のものを選ぶ。"""
    cands = [n for n in entry['natures'] if (NATURE_BOOSTS.get(n['name']) or '@') in pattern]
    pool = cands or entry['natures']
    return max(pool, key=lambda x: x['usage'])['name']


def mega_stone_usage(entry):
    return sum(i['usage'] for i in entry['items'] if 'ite' in i['name'][-5:])


def pick_form(entry):
    """図鑑上の正しい形態名を返す。
    リージョンフォーム（region_form）を最優先で解決してから、メガストーンの採用率で
    メガ形態にするか決める。region_form を見落とすとヒスイダイケンキが通常ダイケンキの
    種族値で計算される、といった事故になる。"""
    base, megas = resolve_form(entry)
    stones = {i['name']: i['usage'] for i in entry['items'] if 'ite' in i['name'][-5:]}
    if sum(stones.values()) >= 50 and megas:
        if len(megas) > 1:
            xs = [k for k in stones if k.endswith('-x')]
            ys = [k for k in stones if k.endswith('-y')]
            if xs and ys:
                return megas[0] if stones[xs[0]] >= stones[ys[0]] else megas[1]
        return megas[0]
    return base


def translate_moves(entry, display_name, missing_moves, translation_warnings):
    """entry['moves']（英語名+採用率）を「日本語技名 (採用率%)」のリストに変換する。
    優先順位: data/move_names_en_ja.json（一次情報）→ LEGACY_USE の同じ並び順（対応表に
    無い技だけのフォールバック）→ どちらにも無ければ警告して英語名のまま残す。
    黙って技を落とすと、その技を計算に使わないぶん被弾が過小評価される。
    翻訳はできたが技データ（MOVES）に無い日本語名は missing_moves に集めてビルドを止める。"""
    legacy = LEGACY_USE.get(display_name, {}).get('moves', [])
    out = []
    for i, mv in enumerate(entry['moves']):
        name_en = mv['name']
        ja = MOVE_NAME_EN_JA.get(name_en)
        if not ja and i < len(legacy):
            ja = legacy[i].split(' (')[0]
        if not ja:
            translation_warnings.add(name_en)
            ja = name_en
        else:
            ja = fix_move_name(ja)
            if ja not in MOVES:
                missing_moves.add(ja)
        out.append(f'{ja} ({mv["usage"]:.1f}%)')
    return out


def build_threats():
    """脅威リストを作る。1体につき、型が複数あれば2行、マルチスケイル持ちはさらに2行に分ける。
    ポケモン名・リージョンフォーム・技データの不整合は黙って除外せず、集めてビルドを止める
    （表から特定のポケモンが消えたことに気づけなくなるため）。"""
    unresolved_pokemon = []
    unresolved_region = []
    for entry in sorted(USAGE, key=lambda x: x['pick_rank']):
        try:
            pick_form(entry)
        except PokemonNotFoundError as e:
            unresolved_pokemon.append(
                f'pokemon_id={e} #{entry["pick_rank"]}位 ({entry.get("pokemon_name_ko", "")})')
        except RegionFormError as e:
            unresolved_region.append(f'{e} #{entry["pick_rank"]}位')

    rows = []
    missing_moves = set()
    translation_warnings = set()
    for entry in sorted(USAGE, key=lambda x: x['pick_rank']):
        if entry['pick_rank'] > THREAT_RANK_LIMIT:
            continue
        try:
            name = pick_form(entry)
        except (PokemonNotFoundError, RegionFormError):
            continue   # 上のループで既に記録済み
        dex = DEX[name]
        stone = mega_stone_usage(entry)
        base_name, _ = resolve_form(entry)
        scarf = sum(i['usage'] for i in entry['items'] if i['name'] == 'choice-scarf')

        for pattern, raw, sps, norm in spread_variants(entry):
            d, display_name, form_note = dex, name, ''
            # メガと逆向きの攻撃方向に振っている型は非メガ運用とみなす
            # （例: メガカイリューはA124<C145の特殊寄り。A振り26%は非メガ率26%と一致する）
            if name.startswith('メガ') and base_name and base_name in DEX and stone < 97:
                mb, bb = dex['base'], DEX[base_name]['base']
                flip_a = 'A' in pattern and 'C' not in pattern and mb[1] < mb[3] and bb[1] > bb[3]
                flip_c = 'C' in pattern and 'A' not in pattern and mb[3] < mb[1] and bb[3] > bb[1]
                if flip_a or flip_c:
                    d, display_name, form_note = DEX[base_name], base_name, '非メガ'

            ability = (d['ab'] if display_name.startswith('メガ')
                       else max(entry['abilities'], key=lambda x: x['usage'])['name'])
            has_multiscale = 'マルチスケイル' in (d['ab'] or '') or 'multiscale' in (ability or '')
            nature = pick_nature(entry, pattern)
            st = stats(d['base'], [sps[k] for k in STAT_KEYS], nature)
            moves_raw = translate_moves(entry, display_name, missing_moves, translation_warnings)
            moves_ja = [x.split(' (')[0] for x in moves_raw]

            for hp_full in ([True, False] if has_multiscale else [None]):
                rows.append(dict(
                    rank=entry['pick_rank'], name=display_name, pattern=pattern,
                    share=round(norm), multi=len(spread_variants(entry)) >= 2,
                    form=form_note, hp_full=hp_full, nature=NAT_JA.get(nature, nature),
                    types=(d['t1'], d['t2']), st=st, ability=ability,
                    speed=int(st[5] * (1.5 if scarf >= 50 else 1)), scarf=scarf >= 50,
                    item=ITEM_JA.get(entry['items'][0]['name'], entry['items'][0]['name'])
                    if entry['items'] else '',
                    moves_ja=moves_ja, moves_raw=moves_raw,
                ))

    if unresolved_pokemon or unresolved_region or missing_moves:
        lines = ['使用率データの取り込みに失敗しました:']
        if unresolved_pokemon:
            lines.append('  図鑑に無いポケモン（新規解禁の可能性。data/ポケモン図鑑.xlsx に追加してください）:')
            lines += [f'    {x}' for x in unresolved_pokemon]
        if unresolved_region:
            lines.append('  リージョンフォームが解決できない'
                         '（図鑑にその形態を追加するか engine.REGION_KEYWORD を見直してください）:')
            lines += [f'    {x}' for x in unresolved_region]
        if missing_moves:
            lines.append('  技データシートに無い技（data/ポケモン図鑑.xlsx の技データに行を追加してください）:')
            lines += [f'    {x}' for x in sorted(missing_moves)]
        print('\n'.join(lines))
        sys.exit(1)

    if translation_warnings:
        print('警告: data/move_names_en_ja.json に無い技があります'
             '（英語名のまま表示し、被弾の計算には使いません。対応表に追記してください）:')
        for w in sorted(translation_warnings):
            print(f'  {w}')

    return rows


# ---------------------------------------------------------------- ダメージ計算

def sr_damage(threat):
    """自分がステルスロックを設置している場合に、相手が受けるダメージ。
    最大HP × いわタイプ相性 / 8 を切り捨て。マジックガードは無効化する。
    ひこうタイプにも入る（まきびしと違い、接地していなくても受ける）。"""
    ab = threat['ability'] or ''
    if ab == 'magic-guard' or 'マジックガード' in ab:
        return 0
    t = eff('いわ', *threat['types'])
    return int(threat['st'][0] * t / 8)


def my_hit(member, move, threat):
    """自軍の1技が相手に与えるダメージ。変化技はNone、一撃必殺は別扱い。"""
    if move in STATUS_MOVES:
        return None
    if move in OHKO_MOVES:
        return dict(move=move, ohko=True, acc=MOVES[move]['acc'])
    m = MOVES[move]
    move_type, extra = m['type'], 1.0
    if member['fairy_skin'] and move_type == 'ノーマル':
        move_type, extra = 'フェアリー', 1.2
    if member['sharpness'] and move in SLASH_MOVES:
        extra *= 1.5
    if member['life_orb']:
        extra *= 1.3
    t = eff(move_type, *threat['types'])
    am, ab_name = ability_mod(threat['ability'], move_type, member['mold_breaker'],
                              hp_full=(threat['hp_full'] is not False),
                              is_sound=(move in SOUND))
    if ab_name == 'ハードロック' and t < 2:
        am = 1.0
    if ab_name == 'ばけのかわ':
        am = 1.0
    stab = 1.5 if move_type in member['types'] else 1.0
    atk = member['st'][1] if m['cat'] == '物理' else member['st'][3]
    dfn = threat['st'][2] if m['cat'] == '物理' else threat['st'][4]
    lo, hi = damage(m['power'], atk, dfn, stab, t * am, extra)
    hp = threat['st'][0]
    # 表示用は「タイプ相性」と「防御特性による補正」を分ける。
    # 両者を掛けた数字だけ出すと、マルチスケイルで半減された2倍が ×1.0 に見えてしまう。
    result = dict(move=move, lo=lo, hi=hi, pl=round(lo * 100 / hp), ph=round(hi * 100 / hp),
                  eff=t, verdict=verdict(lo, hi, hp))
    if am != 1.0 and ab_name:
        result['ab_name'] = ab_name
        result['ab_mult'] = am
    if m['acc'] and m['acc'] < 100:
        result['acc'] = m['acc']
    return result


def boosted_hit(member, threat):
    """積み技を1回使った後の最大打点。積み技を持たない駒はNone。"""
    if not member['boosting_move']:
        return None
    boosted = dict(member)
    boosted['st'] = list(member['st'])
    boosted['st'][1] = int(member['st'][1] * 1.5)
    boosted['st'][3] = int(member['st'][3] * 1.5)
    hits = [my_hit(boosted, mv, threat) for mv in member['moves']]
    hits = [h for h in hits if h and not h.get('ohko')]
    return max(hits, key=lambda x: x['hi']) if hits else None


def their_hit(threat, member):
    """相手の最大打点（自軍の実数値に対して）。"""
    best = None
    for mv in threat['moves_ja'][:8]:
        m = MOVES.get(mv)
        if not m or not m['power']:
            continue
        t = eff(m['type'], *member['types'])
        stab = 1.5 if m['type'] in threat['types'] else 1.0
        atk = threat['st'][1] if m['cat'] == '物理' else threat['st'][3]
        dfn = member['st'][2] if m['cat'] == '物理' else member['st'][4]
        lo, hi = damage(m['power'], atk, dfn, stab, t)
        if not best or hi > best['hi']:
            best = dict(move=mv, lo=lo, hi=hi,
                        pl=round(lo * 100 / member['st'][0]),
                        ph=round(hi * 100 / member['st'][0]))
    return best or dict(move='—', lo=0, hi=0, pl=0, ph=0)


def choose_move(hits):
    """主表示する技と、次善の技を選ぶ。
    判定が最も良い技を主にし、同判定ならデメリットのない技（はかいこうせん以外）を優先する。"""
    attacks = [h for h in hits if h and not h.get('ohko')]
    if not attacks:
        return None, None
    attacks = sorted(attacks, key=lambda m: (-VERDICT_RANK.get(m['verdict'], 0),
                                             m['move'] in DRAWBACK_MOVES, -m['lo']))
    primary = attacks[0]
    alt = None
    for m in attacks[1:]:
        if (m['verdict'] != primary['verdict']
                or m['move'] in DRAWBACK_MOVES or primary['move'] in DRAWBACK_MOVES):
            alt = m
            break
    return primary, alt


def build_members():
    """party.py の定義から実数値つきのメンバーリストを作る。"""
    out = []
    for p in PARTY:
        dex = DEX[p['species']]
        st = stats(dex['base'], p['ev'], p['nature'])
        m = dict(p)
        m['st'] = st
        m['types'] = (dex['t1'], dex['t2'])
        m['speed'] = int(st[5] * 1.5) if p.get('scarf') else st[5]
        out.append(m)
    return out


# ---------------------------------------------------------------- HTML出力

def bar(pl, ph, color):
    a, b = min(pl, 100), min(ph, 100)
    return (f'<div class="trk"><div class="half"></div>'
            f'<div class="fill hi" style="width:{b}%;background:{color}"></div>'
            f'<div class="fill" style="width:{a}%;background:{color}"></div></div>')


def render_card(threat, members, card_id):
    tc = TYPE_COLOR.get(threat['types'][0], '#666')
    type_label = threat['types'][0] + (f"/{threat['types'][1]}" if threat['types'][1] else '')

    chips = ''
    if threat['multi']:
        chips += f'<span class="pat">{threat["pattern"]} {threat["share"]}%</span>'
    if threat['form']:
        chips += f'<span class="pat alt">{threat["form"]}</span>'
    if threat['hp_full'] is True:
        chips += '<span class="pat alt">マルチスケイル有効</span>'
    if threat['hp_full'] is False:
        chips += '<span class="pat ms-off">マルチスケイル解除</span>'

    move_chips = ''
    for raw in threat['moves_raw'][:8]:
        nm = raw.split(' (')[0]
        pct = raw.split(' (')[1].rstrip('%)') if ' (' in raw else ''
        m = MOVES.get(nm)
        is_attack = m and m['power']
        extra = f' {MULTI_HIT[nm]}' if nm in MULTI_HIT else ''
        label = f'<b>{nm}</b>' if is_attack else nm
        move_chips += (f'<span class="mv{"" if is_attack else " st"}">{label} '
                       f'<i>{pct}%{extra}</i></span>')

    sr_dmg = sr_damage(threat)
    hp = threat['st'][0]

    rows = ''
    for member in members:
        hits = [my_hit(member, mv, threat) for mv in member['moves']]
        primary, alt = choose_move(hits)
        if not primary:
            continue
        vclass, vcolor = VERDICT_CLASS.get(primary['verdict'], ('v5', 'var(--weak)'))
        back = their_hit(threat, member)
        danger = ' dg' if back['ph'] >= 100 else ''
        faster = member['speed'] > threat['speed']

        tags = ''
        if primary.get('ab_name'):
            tags += (f' <span class="abm">{primary["ab_name"]}×{primary["ab_mult"]}</span>')
        if primary['move'] in DRAWBACK_MOVES:
            tags += ' <span class="rl">反動</span>'
        if primary.get('acc'):
            tags += f' <span class="ac">命中{primary["acc"]:.0f}%</span>'
        ohko = [h for h in hits if h and h.get('ohko')]
        if ohko:
            tags += f' <span class="ohko">＋{ohko[0]["move"]} {ohko[0]["acc"]:.0f}%</span>'

        sub = ''
        if sr_dmg:
            sr_verdict = verdict(primary['lo'], primary['hi'], max(hp - sr_dmg, 1))
            if sr_verdict != primary['verdict']:
                sub += f'<div class="sr">SR込み: {sr_verdict}</div>'
        if alt:
            atags = ''
            if alt.get('ab_name'):
                atags += f' <span class="abm">{alt["ab_name"]}×{alt["ab_mult"]}</span>'
            if alt['move'] in DRAWBACK_MOVES:
                atags += ' <span class="rl">反動</span>'
            if alt.get('acc'):
                atags += f' <span class="ac">命中{alt["acc"]:.0f}%</span>'
            cls = 'alt up' if VERDICT_RANK[alt['verdict']] > VERDICT_RANK[primary['verdict']] else 'alt'
            sub += (f'<div class="{cls}">{alt["move"]}{atags}: '
                    f'{alt["pl"]}-{alt["ph"]}% {alt["verdict"]}</div>')
        boosted = boosted_hit(member, threat)
        if boosted:
            sub += (f'<div class="d1">{member["boosting_move"]}+1: {boosted["move"]} '
                    f'{boosted["pl"]}-{boosted["ph"]}% {boosted["verdict"]}</div>')

        form_label = f'<small>{member["form"]}</small>' if member['form'] else ''
        rows += (
            f'<tr class="{"nonmega" if member["form"] == "非メガ" else ""}">'
            f'<td class="me">{member["name"]}{form_label}'
            f'<span class="spd {"up" if faster else "dn"}">{"先手" if faster else "後手"}</span></td>'
            f'<td class="hit"><b>{primary["move"]}</b> {primary["lo"]}-{primary["hi"]} '
            f'<span class="mul">×{primary["eff"]}</span>{tags}{sub}</td>'
            f'<td class="barcell">{bar(primary["pl"], primary["ph"], vcolor)}</td>'
            f'<td class="vdcell"><span class="vd {vclass}">{primary["verdict"]}</span></td>'
            f'<td class="pct">{primary["pl"]}-{primary["ph"]}%</td>'
            f'<td class="back{danger}">被弾 <b>{back["move"]}</b> {back["ph"]}%</td></tr>')

    st = threat['st']
    return (
        f'<section class="card" id="{card_id}" data-n="{html.escape(threat["name"])}" '
        f'style="--tc:{tc}">'
        f'<div class="chead"><span class="rk">#{threat["rank"]}</span>'
        f'<span class="nm">{html.escape(threat["name"])}</span>{chips}'
        f'<span class="tag">{type_label}・<b{" class=off" if threat["hp_full"] is False else ""}>'
        f'{ABILITY_JA.get(threat["ability"], threat["ability"])}</b>・'
        f'{threat["item"]}・{threat["nature"]}</span>'
        f'<span class="stats">H<b>{st[0]}</b> A<b>{st[1]}</b> B<b>{st[2]}</b> C<b>{st[3]}</b> '
        f'D<b>{st[4]}</b> S<b>{threat["speed"]}</b>{"★" if threat["scarf"] else ""}</span>'
        f'<a class="top" href="#idx">↑</a></div>'
        f'<div class="mvrow">{move_chips}</div>'
        f'<table><thead><tr><th>味方</th><th>最大打点</th><th>ダメージ</th>'
        f'<th>判定</th><th>%</th><th>被弾</th></tr></thead><tbody>{rows}</tbody></table></section>')


EXPECTED = {
    'ギャラドス': {'メガ': [171, 207, 130, 81, 150, 146], '非メガ': [171, 177, 100, 72, 120, 146]},
    'キラフロル': {'': [159, 67, 111, 182, 101, 151]},
    'エルレイド': {'': [169, 194, 87, 76, 135, 106]},
    'カバルドン': {'': [215, 132, 154, 79, 124, 67]},
    'ドリュウズ': {'スカーフ': [187, 205, 80, 63, 85, 140]},
    'チルタリス': {'メガ': [181, 117, 130, 178, 125, 103], '非メガ': [181, 81, 110, 134, 125, 103]},
}


def verify(members):
    """party.py の設定から出た実数値が期待値と一致するか確認する。
    ゲーム内の表示と突き合わせた値を EXPECTED に置いてある。"""
    bad = []
    for m in members:
        want = EXPECTED.get(m['name'], {}).get(m['form'])
        if want and m['st'] != want:
            bad.append(f"  {m['name']}{m['form']}: 期待 {want} / 実際 {m['st']}")
    if bad:
        print('実数値が期待値と一致しません。ev か nature の設定を確認してください:')
        print('\n'.join(bad))
        sys.exit(1)


def main():
    members = build_members()
    verify(members)
    threats = build_threats()

    cards, index_links = [], []
    for i, t in enumerate(threats):
        cid = f'p{i}'
        label = t['name']
        if t['multi']:
            label += ' ' + t['pattern']
        if t['form']:
            label += ' ' + t['form']
        if t['hp_full'] is True:
            label += ' MS有効'
        if t['hp_full'] is False:
            label += ' MS解除'
        color = TYPE_COLOR.get(t['types'][0], '#666')
        index_links.append(f'<a href="#{cid}" style="--tc:{color}">{html.escape(label)}</a>')
        cards.append(render_card(t, members, cid))

    css = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'style.css'),
               encoding='utf-8').read()
    js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.js'),
              encoding='utf-8').read()

    doc = f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#12151d"><meta name="apple-mobile-web-app-capable" content="yes">
<title>対面ダメージ表</title><style>{css}</style></head><body>
<header><div class="bar"><h1>対面ダメージ表</h1>
<span id="tools" hidden style="display:contents">
<input id="q" type="search" placeholder="相手の名前（ガブ / ミミ / ブリジュ…）"
 autocomplete="off" autocorrect="off" autocapitalize="off">
<span class="tgs"><button class="tg" id="tM" aria-pressed="true">非メガも表示</button></span>
<span class="count" id="cnt"></span></span>
</div></header>
<main>
<nav id="idx"><span class="lbl">目次 — タップで移動（{len(index_links)}件）</span>{''.join(index_links)}</nav>
{''.join(cards)}
<p class="note">メガシンカ後の実数値で計算。ステルスロック・天候・いかく・積みは未計算（積み技は各行に併記）。
型の%は判明している配分の中での比率。★はこだわりスカーフ込みの素早さ。
バーは相手のHP全体に対するダメージ幅で、濃い部分が最低乱数、薄い部分が最高乱数。中央の線が50%。<br>
技は判定が同じならデメリットのない方を優先して表示している。2行目は次善の選択肢で、
<span style="color:#7fd4ff">水色は判定が上がる技</span>。「反動」は撃った次のターンに交代できない技。
「命中◯%」は必中でない技。「SR込み」は自分がステルスロックを設置済みで、相手が満タンの状態で
場に出てステルスロックを受けた場合の判定変化（マジックガードは無効）。判定が変わらない相手には出さない。</p>
</main>
<script>{js}</script></body></html>'''

    out = os.path.join(ROOT, 'index.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(doc)
    print(f'書き出し完了: {out}')
    print(f'  相手 {len(threats)} 行 / 味方 {len(members)} 体 / {len(doc) // 1024} KB')


if __name__ == '__main__':
    main()
