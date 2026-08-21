#!/usr/bin/env python3
"""
相手の型を作り、ダメージを計算する。データの整合性チェックもここ。

    python build/generate.py        データを検証する（生成物は作らない）

以前はここで index.html を書き出していたが、表示はブラウザ側（assets/app.js）に移した。
このモジュールは相手の型を組む処理（配分の集約・メガ形態の判定・リージョンフォーム・
マルチスケイルやへんげんじざいの行分割）と、ダメージ計算の本体を持つ。
ブラウザが読む JSON は build/export_app_data.py がここを呼んで書き出す。

JS 側（assets/engine.js）はこの計算の移植版。数字を変えたら
appdata/golden.json を作り直して node build/verify_engine.js を通すこと。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import (ROOT, DEX, MOVES, USAGE, BY_DEX_NO, NAT_JA, resolve_form,
                    MOVE_NAME_EN_JA, ABILITIES, fix_move_name, is_mega,
                    PokemonNotFoundError, RegionFormError,
                    stats, eff, ability_mod, damage, verdict, VERDICT_RANK, SOUND,
                    self_boost, rank_multiplier, multi_damage, verdict_plus_one)
from party import (PARTY, DRAWBACK_MOVES, SLASH_MOVES, OHKO_MOVES, STATUS_MOVES,
                   CONTACT_MOVES, NON_CONTACT_MOVES,
                   THREAT_RANK_LIMIT, SPREAD_THRESHOLD, RARE_MOVE_THRESHOLD)

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
# 相手が持ちうる特性を、この表の計算にどう反映しているかの一覧。
# 効果の説明は data/abilities_ja.json（build/extract_abilities.py が data/特性の効果.pdf から生成）を見る。
# 使用率データを新しい月に差し替えたとき、ここに無い特性が出てきたら警告する。
# 「黙って無視した結果、打点や被弾がズレていることに気づけない」のを防ぐのが目的なので、
# 新しい特性が出たら必ずここに1行足して、反映するのか無視するのかを決めること。
ABILITY_HANDLING = {
    # --- ability_mod() で反映済み（相手の防御特性） ---
    'あついしぼう': '反映済み: ほのお・こおりを0.5倍',
    'ふゆう': '反映済み: じめん無効',
    'マルチスケイル': '反映済み: 満タン時0.5倍。行を2つに分けている',
    'ばけのかわ': '反映済み: 等倍で出しターン+1として扱う',

    # --- 打点にも被弾にも影響しない（変化技・状態異常・素早さ・PPなど） ---
    'あまのじゃく': '影響なし: 能力変化の向きのみ',
    'あめふらし': '影響なし: 天候は未計算',
    'ひでり': '影響なし: 天候は未計算',
    'すなおこし': '影響なし: 天候は未計算',
    'ゆきふらし': '影響なし: 天候は未計算',
    'いたずらごころ': '影響なし: 変化技の優先度のみ',
    'おうごんのからだ': '影響なし: 変化技を無効化するだけ',
    'マジックミラー': '影響なし: 変化技を跳ね返すだけ',
    'かげふみ': '影響なし: 交代の制限のみ',
    'かそく': '影響なし: 素早さランクのみ',
    'すいすい': '影響なし: あめ時の素早さのみ。天候は未計算',
    'くだけるよろい': '影響なし: 被弾後のランク変化のみ',
    'じきゅうりょく': '影響なし: 被弾後のランク変化のみ',
    'すりぬけ': '影響なし: 壁や身代わりの貫通のみ',
    'せいしんりょく': '影響なし: ひるみ無効のみ',
    'ノーガード': '影響なし: 命中のみ。命中率は技ごとに別途表示',
    'プレッシャー': '影響なし: PPのみ',
    'ほのおのからだ': '影響なし: 接触時のやけど。状態異常は未計算',
    'さめはだ': '影響なし: 接触時の定数ダメージ。打点・被弾の数値そのものは変わらない',
    'どくげしょう': '影響なし: 被弾時のどくびし設置',
    'かたやぶり': '影響なし: 相手側が持っていても、こちらの防御特性は元々計算に入れていない',

    # --- their_hit() で反映済み（相手の攻撃特性。被弾に効く） ---
    'かたいツメ': '反映済み: 接触技1.3倍。接触判定は party.CONTACT_MOVES',
    'ちからもち': '反映済み: 物理の攻撃2倍',
    'ヨガパワー': '反映済み: 物理の攻撃2倍',
    'てきおうりょく': '反映済み: タイプ一致が2.0倍',
    'テクニシャン': '反映済み: 威力60以下が1.5倍',
    'きれあじ': '反映済み: 斬撃技1.5倍。対象は party.SLASH_MOVES',
    'メガソーラー': '反映済み: 自分だけ常ににほんばれ。ウェザーボールがほのお威力100、'
                    'ほのお技1.5倍・みず技0.5倍。ソーラービームは溜めなしなので威力120のまま',
    'へんげんじざい': '反映済み: 発動・未発動で行を2つに分ける',
    'リベロ': '反映済み: へんげんじざいと同じ扱い',

    # --- 未反映（影響はあるが入れていない） ---
    'きもったま': '未反映: ノーマル・かくとうがゴーストに通る。今のパーティにゴーストが居ない',
    'バトルスイッチ': '未反映: 攻撃時に形態が変わり実数値が動く（ギルガルド）',

    # --- 条件付き。積みや天候と同じ扱いで、素の値を出す方針から外している ---
    'げきりゅう': '未反映: HP1/3以下での1.5倍。積みと同じく条件付きなので入れない',
    'しんりょく': '未反映: HP1/3以下でのくさ技1.5倍。げきりゅうと同じ扱い',
    'リーフガード': '影響なし: にほんばれ時の状態異常無効のみ',
    'てんねん': '未反映: ランク補正無視。ランク自体を計算に入れていない',
    'そうだいしょう': '未反映: 味方の瀕死数で上昇。条件付きなので入れない',
    'でんきにかえる': '未反映: 次のでんき技が2倍。条件付きなので入れない',
}

# 連続技の回数表示。技名を並べず技データの効果欄から導く（engine.parse_multi_hit）。
# 手で並べていた頃は ネズミざん・ドラゴンアロー・みずしゅりけん・ツインビーム が漏れていた。
MULTI_HIT = {name: m['multi']['label'] for name, m in MOVES.items() if m['multi']}


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
    対応表 data/move_names_en_ja.json が一次情報で、無ければ警告して英語名のまま残す。
    黙って技を落とすと、その技を計算に使わないぶん被弾が過小評価される。
    翻訳はできたが技データ（MOVES）に無い日本語名は missing_moves に集めてビルドを止める。

    以前は旧使用率シートの「同じ並び順」を最後の砦にしていたが、月が変わると技の順番が
    変わるので別の技名を拾いかねない。当てにならない上に実際に一度も使われていなかったため、
    CSV移行にあわせて外した。"""
    out = []
    for mv in entry['moves']:
        name_en = mv['name']
        ja = MOVE_NAME_EN_JA.get(name_en)
        if not ja:
            translation_warnings.add(name_en)
            ja = name_en
        else:
            ja = fix_move_name(ja)
            if ja not in MOVES:
                missing_moves.add(ja)
        out.append(f'{ja} ({mv["usage"]:.1f}%)')
    return out


def check_abilities(rows):
    """表に出てくる相手の特性が ABILITY_HANDLING で分類済みか確かめる。
    図鑑側の特性欄は「しんりょくリーフガード」のように複数の特性が繋がっているので、
    ability_mod() と同じく部分一致で照合する。
    未分類が出たら、その特性を計算に入れるかどうか判断されないまま表が出てしまうので警告する。"""
    unknown = {}
    unclassified_contact = {}
    for r in rows:
        ability = ABILITY_JA.get(r['ability'], r['ability']) or ''
        if not any(k in ability for k in ABILITY_HANDLING):
            unknown.setdefault(ability, set()).add(r['name'])
        # かたいツメは接触技だけ1.3倍。接触かどうか分からない技があると、
        # 黙って等倍に落として被弾を低く見せてしまうので拾っておく。
        if 'かたいツメ' in ability:
            for mv in r['moves_ja'][:8]:
                m = MOVES.get(mv)
                if m and m['power'] and mv not in CONTACT_MOVES and mv not in NON_CONTACT_MOVES:
                    unclassified_contact.setdefault(mv, set()).add(r['name'])

    if unknown:
        print('警告: 計算に入れるか未判断の特性があります'
              '（build/generate.py の ABILITY_HANDLING に追記してください）:')
        for ability, names in sorted(unknown.items()):
            effect = ABILITIES.get(ability, '（data/abilities_ja.json に説明なし）')
            print(f'  {ability} — {effect}')
            print(f'    該当: {"、".join(sorted(names))}')

    if unclassified_contact:
        print('警告: かたいツメ持ちが使う技のうち、接触かどうか未分類のものがあります'
              '（build/party.py の CONTACT_MOVES / NON_CONTACT_MOVES に追記してください）:')
        for mv, names in sorted(unclassified_contact.items()):
            print(f'  {mv} — 該当: {"、".join(sorted(names))}')


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
            if is_mega(name) and base_name and base_name in DEX and stone < 97:
                mb, bb = dex['base'], DEX[base_name]['base']
                flip_a = 'A' in pattern and 'C' not in pattern and mb[1] < mb[3] and bb[1] > bb[3]
                flip_c = 'C' in pattern and 'A' not in pattern and mb[3] < mb[1] and bb[3] > bb[1]
                if flip_a or flip_c:
                    d, display_name, form_note = DEX[base_name], base_name, '非メガ'

            ability = (d['ab'] if is_mega(display_name)
                       else max(entry['abilities'], key=lambda x: x['usage'])['name'])
            has_multiscale = 'マルチスケイル' in (d['ab'] or '') or 'multiscale' in (ability or '')
            # へんげんじざいは「発動して一致が乗る」場合と「発動していない（＝不一致技を撃つ）」
            # 場合で被弾が変わる。マルチスケイルと同じく行を2つに分けて両方出す。
            ability_ja = ABILITY_JA.get(ability, ability) or ''
            has_protean = 'へんげんじざい' in ability_ja or 'リベロ' in ability_ja
            nature = pick_nature(entry, pattern)
            st = stats(d['base'], [sps[k] for k in STAT_KEYS], nature)
            moves_raw = translate_moves(entry, display_name, missing_moves, translation_warnings)
            moves_ja = [x.split(' (')[0] for x in moves_raw]
            # 被弾の計算で「主要技か低採用技か」を分けるために採用率を持っておく
            moves_use = [(x.split(' (')[0],
                          float(x.split(' (')[1].rstrip('%)')) if ' (' in x else 0.0)
                         for x in moves_raw]

            variants = [(h, p)
                        for h in ([True, False] if has_multiscale else [None])
                        for p in ([True, False] if has_protean else [None])]
            for hp_full, protean in variants:
                rows.append(dict(
                    rank=entry['pick_rank'], name=display_name, pattern=pattern,
                    share=round(norm), multi=len(spread_variants(entry)) >= 2,
                    form=form_note, hp_full=hp_full, protean=protean,
                    nature=NAT_JA.get(nature, nature),
                    types=(d['t1'], d['t2']), st=st, ability=ability,
                    speed=int(st[5] * (1.5 if scarf >= 50 else 1)), scarf=scarf >= 50,
                    item=ITEM_JA.get(entry['items'][0]['name'], entry['items'][0]['name'])
                    if entry['items'] else '',
                    moves_ja=moves_ja, moves_raw=moves_raw, moves_use=moves_use,
                ))

    if unresolved_pokemon or unresolved_region or missing_moves:
        lines = ['使用率データの取り込みに失敗しました:']
        if unresolved_pokemon:
            lines.append('  図鑑に無いポケモン（新規解禁の可能性。data/dex.csv に行を追加してください）:')
            lines += [f'    {x}' for x in unresolved_pokemon]
        if unresolved_region:
            lines.append('  リージョンフォームが解決できない'
                         '（図鑑にその形態を追加するか engine.REGION_KEYWORD を見直してください）:')
            lines += [f'    {x}' for x in unresolved_region]
        if missing_moves:
            lines.append('  技データに無い技（data/moves.csv に行を追加してください）:')
            lines += [f'    {x}' for x in sorted(missing_moves)]
        print('\n'.join(lines))
        sys.exit(1)

    if translation_warnings:
        print('警告: data/move_names_en_ja.json に無い技があります'
             '（英語名のまま表示し、被弾の計算には使いません。対応表に追記してください）:')
        for w in sorted(translation_warnings):
            print(f'  {w}')

    check_abilities(rows)
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


def my_hit(member, move, threat, hp_eff=None):
    """自軍の1技が相手に与えるダメージ。変化技はNone、一撃必殺は別扱い。
    hp_eff は判定・%の分母に使う相手のHP。ステルスロック込みの表を作るときに
    「最大HP - SRダメージ」を渡す。ダメージの実数値（lo/hi）自体は変わらない。"""
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
    disguise = (ab_name == 'ばけのかわ')
    if disguise:
        am = 1.0        # 倍率ではなく1回無効なので、ダメージは等倍のまま
    stab = 1.5 if move_type in member['types'] else 1.0
    atk = member['st'][1] if m['cat'] == '物理' else member['st'][3]
    dfn = threat['st'][2] if m['cat'] == '物理' else threat['st'][4]
    if m['multi']:
        lo, hi = multi_damage(m['multi'], m['power'], atk, dfn, stab, t * am, extra)
    else:
        lo, hi = damage(m['power'], atk, dfn, stab, t * am, extra)
    hp = threat['st'][0] if hp_eff is None else hp_eff
    # 表示用は「タイプ相性」と「防御特性による補正」を分ける。
    # 両者を掛けた数字だけ出すと、マルチスケイルで半減された2倍が ×1.0 に見えてしまう。
    v = verdict(lo, hi, hp)
    if disguise:
        # 皮で1回止まるぶん、倒すのに必要な手数が1つ増える
        v = verdict_plus_one(v)
    result = dict(move=move, lo=lo, hi=hi, pl=round(lo * 100 / hp), ph=round(hi * 100 / hp),
                  eff=t, verdict=v)
    if disguise:
        result['disguise'] = True
    if m['multi']:
        result['hits'] = m['multi']['label']
    if am != 1.0 and ab_name:
        result['ab_name'] = ab_name
        result['ab_mult'] = am
    if m['acc'] and m['acc'] < 100:
        result['acc'] = m['acc']
    return result


def boosted_hit(member, threat, hp_eff=None):
    """積み技を1回使った後の最大打点。積み技を持たない駒はNone。
    上がるのはその技が実際に上げる能力だけで、段階もその技のぶん。
    つるぎのまいは攻撃+2なので2.0倍、りゅうのまいは攻撃+1なので1.5倍になる。
    以前は技を問わず攻撃・特攻を一律1.5倍していたので、+2の技で過小評価していた。"""
    move = member['boosting_move']
    if not move:
        return None
    boost = self_boost(move)
    if not boost:
        return None
    boosted = dict(member)
    boosted['st'] = list(member['st'])
    for stat, idx in (('atk', 1), ('spa', 3)):
        if stat in boost:
            boosted['st'][idx] = int(member['st'][idx] * rank_multiplier(boost[stat]))
    hits = [my_hit(boosted, mv, threat, hp_eff) for mv in member['moves']]
    hits = [h for h in hits if h and not h.get('ohko')]
    if not hits:
        return None
    best = max(hits, key=lambda x: x['hi'])
    best['stages'] = max(boost.values())
    return best


def their_hit(threat, member):
    """相手の最大打点（自軍の実数値に対して）。
    相手の攻撃特性（使用率が最も高いもの＝threat['ability']）と、
    自軍の防御特性の両方を反映する。
    補正の掛け方は my_hit と揃える: 威力と攻撃は基礎ダメージ、タイプ一致は stab、
    残りは extra（その他補正）。順番を変えると乱数判定が1〜2ずれる。

    条件で剥がれる特性の扱い:
      マルチスケイル … 主表示は満タン時（半減）、剥がれた後を stripped に入れて併記する。
      ばけのかわ     … 皮がある間はそのターンの攻撃が通らない。0%を主表示にしても
                       役に立たないので、主表示は皮が剥がれた後の数字にして、
                       「皮で1回無効」の印を付ける。
    相手がかたやぶり系ならどちらも無視される。"""
    ability = ABILITY_JA.get(threat['ability'], threat['ability']) or ''
    mold = any(k in ability for k in ('かたやぶり', 'ターボブレイズ', 'テラボルテージ'))
    my_ab = member.get('ability') or ''
    has_ms = ('マルチスケイル' in my_ab) and not mold
    has_disguise = ('ばけのかわ' in my_ab) and not mold

    def scan(defender_ability_on):
        return _their_hit_scan(threat, member, ability, mold, defender_ability_on)

    if has_disguise:
        best = scan(False)                     # 皮が剥がれた後の数字を主表示にする
        if best['move'] != '—':
            best['disguise'] = True
        return best
    best = scan(True)
    if has_ms and best['move'] != '—':
        stripped = scan(False)
        if stripped['move'] != '—' and stripped['hi'] > best['hi']:
            best['stripped'] = stripped
            best['stripped_label'] = 'マルチスケイル解除'
    return best


def _their_hit_scan(threat, member, ability, mold, defender_ability_on):
    """their_hit の本体。自軍の防御特性を効かせるかどうかを切り替えて2回呼ぶ。"""
    main, rare = [], []
    for mv, usage in threat['moves_use'][:8]:
        m = MOVES.get(mv)
        if not m or not m['power']:
            continue
        move_type, power, extra = m['type'], m['power'], 1.0
        atk = threat['st'][1] if m['cat'] == '物理' else threat['st'][3]

        # メガソーラー（メガメガニウム）は、実際の天候に関わらず自分の行動だけを
        # にほんばれ状態として扱う。ウェザーボールがほのお・威力100に変わるのが大きく、
        # 素の ノーマル・威力50 のまま計算すると被弾を大幅に見誤る。
        # ソーラービームは溜めなし・威力低下なしなので、そのまま威力120で扱ってよい。
        if 'メガソーラー' in ability:
            if mv == 'ウェザーボール':
                move_type, power = 'ほのお', 100.0
            if move_type == 'ほのお':
                extra *= 1.5
            elif move_type == 'みず':
                extra *= 0.5

        if 'テクニシャン' in ability and power <= 60:
            power *= 1.5
        if ('ちからもち' in ability or 'ヨガパワー' in ability) and m['cat'] == '物理':
            atk *= 2
        if 'きれあじ' in ability and mv in SLASH_MOVES:
            extra *= 1.5
        if 'かたいツメ' in ability and mv in CONTACT_MOVES:
            extra *= 1.3

        if threat['protean']:
            stab = 1.5          # へんげんじざいが発動した技は必ずタイプ一致になる
        elif 'てきおうりょく' in ability and move_type in threat['types']:
            stab = 2.0
        else:
            stab = 1.5 if move_type in threat['types'] else 1.0

        t = eff(move_type, *member['types'])

        # 自軍の防御特性。あついしぼう・ふゆう・マルチスケイルなどが効く。
        # ばけのかわは倍率ではないのでここでは触らず、呼び出し側で扱う。
        am = 1.0
        if defender_ability_on:
            am, ab_name = ability_mod(member.get('ability'), move_type, mold,
                                      hp_full=True, is_sound=(mv in SOUND))
            if ab_name == 'ハードロック' and t < 2:
                am = 1.0
            if ab_name == 'ばけのかわ':
                am = 1.0

        if t * am == 0:
            continue    # タイプ相性か特性で通らない技。damage() は最低1を返すので、
                        # ここで落とさないと「じしん 1%」が主表示になってしまう
        dfn = member['st'][2] if m['cat'] == '物理' else member['st'][4]
        if m['multi']:
            lo, hi = multi_damage(m['multi'], power, atk, dfn, stab, t * am, extra)
        else:
            lo, hi = damage(power, atk, dfn, stab, t * am, extra)
        cand = dict(move=mv, lo=lo, hi=hi, usage=usage,
                    pl=round(lo * 100 / member['st'][0]),
                    ph=round(hi * 100 / member['st'][0]))
        if m['multi']:
            cand['hits'] = m['multi']['label']
        (main if usage > RARE_MOVE_THRESHOLD else rare).append(cand)

    # 主表示は採用率が閾値を超える技の中での最大打点。低採用の技しか無いポケモンだけ、
    # 仕方なくそちらを使う（何も出ないと被弾が空欄になってしまうため）。
    pool = main or rare
    if not pool:
        return dict(move='—', lo=0, hi=0, pl=0, ph=0)
    best = max(pool, key=lambda x: x['hi'])
    # 低採用の技が主要技を上回るときだけ、補足として持たせる
    if main and rare:
        top_rare = max(rare, key=lambda x: x['hi'])
        if top_rare['hi'] > best['hi']:
            best = dict(best, rare=top_rare)
    return best


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
    """データの整合性を確かめる。以前はここで index.html を書き出していたが、
    表示はブラウザ側（assets/app.js）に移したので、生成物は作らない。
    パーティの実数値検証・図鑑や技の欠落・特性の未分類は、build_threats() と
    verify() の中でチェックしてエラーや警告を出す。
    ブラウザが読む JSON は build/export_app_data.py が書き出す。"""
    members = build_members()
    verify(members)
    threats = build_threats()
    print('検証完了')
    print(f'  相手 {len(threats)} 行 / 味方 {len(members)} 体')
    print('  ブラウザ用データを作るには: python build/export_app_data.py')


if __name__ == '__main__':
    main()
