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
                    IMMUNE_JA, IMMUNE_EN, HALF_JA, HALF_EN, DOUBLE_JA, DOUBLE_EN,
                    stats, eff, move_eff, ability_mod, damage, verdict, VERDICT_RANK, SOUND,
                    self_boost, rank_multiplier, multi_damage, verdict_plus_one)
from party import (PARTY, DRAWBACK_MOVES, SLASH_MOVES, OHKO_MOVES, STATUS_MOVES,
                   CONTACT_MOVES, NON_CONTACT_MOVES, PUNCH_MOVES,
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
    # --- 追加分 ---
    'huge-power': 'ちからもち', 'pure-power': 'ヨガパワー', 'technician': 'テクニシャン',
    'thick-fat': 'あついしぼう', 'heatproof': 'たいねつ', 'water-bubble': 'すいほう',
    'flash-fire': 'もらいび', 'water-absorb': 'ちょすい', 'earth-eater': 'どしょく',
    'pixilate': 'フェアリースキン', 'refrigerate': 'フリーズスキン',
    'aerilate': 'スカイスキン', 'galvanize': 'エレキスキン',
    'iron-fist': 'てつのこぶし', 'fluffy': 'もふもふ', 'sturdy': 'がんじょう',
    'skill-link': 'スキルリンク', 'compound-eyes': 'ふくがん',
    'parental-bond': 'おやこあい', 'fairy-aura': 'フェアリーオーラ',
    'contrary': 'あまのじゃく', 'competitive': 'かちき', 'defiant': 'まけんき',
    'speed-boost': 'かそく', 'unburden': 'かるわざ', 'gooey': 'ぬめぬめ',
    'intimidate': 'いかく', 'regenerator': 'さいせいりょく', 'effect-spore': 'ほうし',
    'cursed-body': 'のろわれボディ', 'illusion': 'イリュージョン', 'imposter': 'かわりもの',
    'magic-bounce': 'マジックミラー', 'shell-armor': 'シェルアーマー',
    'bulletproof': 'ぼうだん', 'lightning-rod': 'ひらいしん',
    'mega-launcher': 'メガランチャー', 'healer': 'いやしのこころ',
    'trace': 'トレース', 'no-guard': 'ノーガード', 'punk-rock': 'パンクロック',
    'libero': 'リベロ', 'sheer-force': 'ちからずく',
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
    # 上位100位まで広げて出てきたメガストーン。ゲーム内の表記を確認できていないものは
    # 「通常形態の名前＋ナイト」という既存の命名にならって置いてある
    # （ゲンガナイト・フシギバナイトのように縮まる例があるので、実物と違ったら直すこと）。
    'banettite': 'ジュペッタナイト', 'blastoisinite': 'カメックスナイト',
    'chandelurite': 'シャンデラナイト', 'chesnaughtite': 'ブリガロンナイト',
    'dragalgite': 'ドラミドロナイト', 'floettite': 'フラエッテナイト',
    'froslassite': 'ユキメノコナイト', 'gardevoirite': 'サーナイトナイト',
    'kangaskhanite': 'ガルーラナイト', 'pyroarite': 'カエンジシナイト',
    'sceptilite': 'ジュカインナイト', 'scolipedite': 'ペンドラーナイト',
    'scovillainite': 'スコヴィランナイト', 'scraftite': 'ズルズキンナイト',
    'skarmorite': 'エアームドナイト', 'slowbronite': 'ヤドランナイト',
    'tyranitarite': 'バンギラスナイト', 'victreebelite': 'ウツボットナイト',
    # ダメージに関わる持ち物（ITEM_DAMAGE で補正を掛ける）
    'choice-band': 'こだわりハチマキ', 'choice-specs': 'こだわりメガネ',
    'expert-belt': 'たつじんのおび', 'mystic-water': 'しんぴのしずく',
    'never-melt-ice': 'とけないこおり', 'spell-tag': 'のろいのおふだ',
    'miracle-seed': 'きせきのタネ', 'fairy-feather': 'フェアリーのはね',
    # ダメージに関わらないが主採用になりうるもの（英語名のまま出さないため）
    'white-herb': 'しろいハーブ', 'mental-herb': 'メンタルハーブ',
    'wide-lens': 'こうかくレンズ', 'scope-lens': 'ピントレンズ',
    'quick-claw': 'せんせいのツメ', 'bright-powder': 'ひかりのこな',
    'heat-rock': 'あついいわ', 'smooth-rock': 'さらさらいわ',
    'light-ball': 'でんきだま',
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
    'かちき': '影響なし: 能力を下げられた後のランクのみ',
    'まけんき': '影響なし: 能力を下げられた後のランクのみ',
    'かるわざ': '影響なし: 持ち物消費後の素早さのみ',
    'ぬめぬめ': '影響なし: 接触時の素早さランクのみ',
    'いかく': '未反映: 登場時に相手のA-1。ランク補正を計算に入れていないので外している',
    'さいせいりょく': '影響なし: 交代時の回復のみ',
    'ほうし': '影響なし: 接触時の状態異常。状態異常は未計算',
    'のろわれボディ': '影響なし: PPのみ',
    'イリュージョン': '影響なし: 見た目のみ。実数値は本人のもの',
    'かわりもの': '未反映: 相手にへんしんするので実数値が定まらない',
    'シェルアーマー': '影響なし: 急所無効のみ。急所は計算に入れていない',
    'ノーガード': '影響なし: 命中のみ',
    'いやしのこころ': '影響なし: ダブル用',
    'トレース': '未反映: 相手の特性をコピーするので事前に定まらない',
    'ぼうだん': '未反映: 弾技の無効化。対象技の一覧を持っていない',
    'ひらいしん': '影響なし: ダブル用の吸い寄せ。でんき無効は IMMUNE 側で反映済み',
    'メガランチャー': '未反映: 波動技1.5倍。対象技の一覧を持っていない',
    'とびだすなかみ': '未反映: 瀕死時に受けたダメージ分を反射。対面表の与ダメージには出ない',
    'とびだすハバネロ': '未反映: 被弾時に相手をやけど。状態異常は未計算',
    'うなぎのぼり': '未反映: ふゆう＋ビーストブースト。ふゆう部分は IMMUNE 側で反映済み',
    'パンクロック': '未反映: 音技1.3倍／受ける音技0.5倍',
    'ちからずく': '未反映: 追加効果を捨てて1.3倍',
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
    'てつのこぶし': '反映済み: パンチ技1.2倍。対象は party.PUNCH_MOVES',
    'ほのおのたてがみ': '反映済み: ほのお技1.5倍',
    'すいほう': '反映済み: 自分のみず技2倍／受けるほのお0.5倍',
    'フェアリースキン': '反映済み: ノーマル技がフェアリーになり1.2倍。SKIN_ABILITIES',
    'スカイスキン': '反映済み: フェアリースキンと同じ枠',
    'フリーズスキン': '反映済み: フェアリースキンと同じ枠',
    'エレキスキン': '反映済み: フェアリースキンと同じ枠',
    'おやこあい': '反映済み: 2回攻撃。2発目は威力1/4。_bond_damage()',
    'フェアリーオーラ': '反映済み: 攻守どちらが持っていてもフェアリー技1.33倍',
    'スキルリンク': '反映済み: 連続技の最低回数を最大回数に固定',
    'ふくがん': '反映済み: 命中1.3倍（表示のみ。ダメージは変わらない）',

    # --- 防御特性（ability_mod で反映済み） ---
    'たいねつ': '反映済み: ほのおを0.5倍',
    'もらいび': '反映済み: ほのお無効',
    'ちょすい': '反映済み: みず無効',
    'どしょく': '反映済み: じめん無効',
    'もふもふ': '反映済み: 接触技0.5倍／ほのお2倍。接触判定は party.CONTACT_MOVES',
    'がんじょう': '反映済み: 満タンからの確1を許さない（手数+1）',

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

    # 持ち物も特性と同じく、分類していないものが出たら知らせる。
    # 黙って等倍にすると、いのちのたま持ちの被弾が1.3倍ぶん低いまま気づけない。
    unknown_items = {}
    for r in rows:
        item = r['item'] or ''
        # メガストーンはメガシンカの引き金であってダメージ補正は無い。
        # 「リザードナイトY」のように末尾にX/Yが付くものがあるので、そこは外して見る。
        stone = item[:-1] if item[-1:] in ('X', 'Y') else item
        if item in ITEM_DAMAGE or item in ITEM_NO_DAMAGE or stone.endswith('ナイト'):
            continue
        unknown_items.setdefault(item, set()).add(r['name'])
    if unknown_items:
        print('警告: ダメージに影響するか未判断の持ち物があります'
              '（build/generate.py の ITEM_DAMAGE か ITEM_NO_DAMAGE に追記してください）:')
        for item, names in sorted(unknown_items.items()):
            print(f'  {item} — 該当: {"、".join(sorted(names))}')

    if unclassified_contact:
        print('警告: かたいツメ持ちが使う技のうち、接触かどうか未分類のものがあります'
              '（build/party.py の CONTACT_MOVES / NON_CONTACT_MOVES に追記してください）:')
        for mv, names in sorted(unclassified_contact.items()):
            print(f'  {mv} — 該当: {"、".join(sorted(names))}')


def build_threats(limit=None):
    """脅威リストを作る。1体につき、型が複数あれば2行、マルチスケイル持ちはさらに2行に分ける。
    ポケモン名・リージョンフォーム・技データの不整合は黙って除外せず、集めてビルドを止める
    （表から特定のポケモンが消えたことに気づけなくなるため）。"""
    limit = THREAT_RANK_LIMIT if limit is None else limit
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
        if entry['pick_rank'] > limit:
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

def _ability_type_mult(ability, atk):
    """防御側の特性が、その攻撃タイプに対して掛ける倍率。特性の影響が無ければ 1.0。

    **タイプごとに効く防御特性だけを見る。** ふゆう・もらいび・ちょすい・どしょく等（無効）、
    あついしぼう・たいねつ・すいほう（半減）、もふもふ（ほのおだけ2倍）。
    マルチスケイル・ハードロック・がんじょう・ばけのかわは**入れない** —
    タイプに依らず全部の倍率を動かすので、入れると「相性」ではなくなる。

    特性名は英語スラッグのことも日本語のこともあるので、両方のテーブルを同じ文字列に当てる。
    1つの特性が複数のテーブルに載ることは無いので、最初に一致したものを返せばよい。"""
    ab = ability or ''
    for table in (IMMUNE_JA, IMMUNE_EN):
        for name, typ in table.items():
            if name in ab and typ == atk:
                return 0.0
    for table in (HALF_JA, HALF_EN):
        for name, typs in table.items():
            if name in ab and atk in typs:
                return 0.5
    for table in (DOUBLE_JA, DOUBLE_EN):
        for name, typs in table.items():
            if name in ab and atk in typs:
                return 2.0
    return 1.0


def ability_type_effects():
    """{特性名: {攻撃タイプ: 倍率}}。選出補助の相性表で JS 側が引くために書き出す。

    JS には「掛け算」だけをさせて、**どの特性を相性に効かせるかの判断はここに残す**。
    表そのものを JS に書き写すと、マルチスケイルを入れるかどうかの線引きが必ず食い違う。
    日本語名だけで足りる（図鑑と party.txt の特性は日本語）。"""
    out = {}
    for name, typ in IMMUNE_JA.items():
        out.setdefault(name, {})[typ] = 0.0
    for name, typs in HALF_JA.items():
        for t in typs:
            out.setdefault(name, {})[t] = 0.5
    for name, typs in DOUBLE_JA.items():
        for t in typs:
            out.setdefault(name, {})[t] = 2.0
    return out


def type_effects(types):
    """そのタイプ構成が受ける、18タイプぶんの素の相性倍率。特性は含まない。
    並びは TYPE_COLOR の順（rules.typeOrder と同じ）。"""
    return [eff(atk, *types) for atk in TYPE_COLOR]


def type_weakness(types, ability):
    """相手の弱点を (4倍以上, 2倍) に分けて返す。表示専用で、ダメージ計算には使わない。
    タイプ別に効く防御特性は反映する（線引きは _ability_type_mult のコメント参照）。"""
    x4, x2 = [], []
    for atk in TYPE_COLOR:
        e = eff(atk, *types) * _ability_type_mult(ability, atk)
        if e >= 4:
            x4.append(atk)
        elif e >= 2:
            x2.append(atk)
    return x4, x2


def sr_damage(threat):
    """自分がステルスロックを設置している場合に、相手が受けるダメージ。
    最大HP × いわタイプ相性 / 8 を切り捨て。マジックガードは無効化する。
    ひこうタイプにも入る（まきびしと違い、接地していなくても受ける）。"""
    ab = threat['ability'] or ''
    if ab == 'magic-guard' or 'マジックガード' in ab:
        return 0
    t = eff('いわ', *threat['types'])
    return int(threat['st'][0] * t / 8)


# ノーマル技を別タイプに変えて威力1.2倍にする特性。タイプ一致も乗る。
SKIN_ABILITIES = {'フェアリースキン': 'フェアリー', 'スカイスキン': 'ひこう',
                  'フリーズスキン': 'こおり', 'ドラゴンスキン': 'ドラゴン',
                  'エレキスキン': 'でんき'}


# 持ち物によるダメージ補正（攻撃側にだけ効くもの）。
#   mult  … その他補正に掛ける倍率
#   type  … 指定があればそのタイプの技だけ
#   super … Trueなら効果抜群のときだけ
#   atk_mult / cat … 攻撃実数値に掛ける倍率と対象の分類
# ここに無い持ち物が相手の主採用になっているとビルドが警告する（黙って等倍にしないため）。
ITEM_DAMAGE = {
    'いのちのたま':     dict(mult=1.3),
    'たつじんのおび':   dict(mult=1.2, super=True),
    'こだわりハチマキ': dict(atk_mult=1.5, cat='物理'),
    'こだわりメガネ':   dict(atk_mult=1.5, cat='特殊'),
    # タイプ強化アイテム（該当タイプの技を1.2倍）
    'くろいメガネ':     dict(mult=1.2, type='あく'),
    'しんぴのしずく':   dict(mult=1.2, type='みず'),
    'のろいのおふだ':   dict(mult=1.2, type='ゴースト'),
    'とけないこおり':   dict(mult=1.2, type='こおり'),
    'きせきのタネ':     dict(mult=1.2, type='くさ'),
    'フェアリーのはね': dict(mult=1.2, type='フェアリー'),
}

# ダメージに影響しない持ち物。分類済みであることを示すためだけに並べてある。
# メガストーンは「ナイト」で終わる名前で判定するので個別には書かない。
ITEM_NO_DAMAGE = {
    # きあいのタスキ: がんじょうと効果は同じだが、あえて反映していない。
    # 同じポケモンでもタスキ型とそうでない型が混在し、型ごとの持ち物は使用率データの
    # 最頻値しか見ていないため、一律に効かせると外れる場面のほうが多くなる。
    # 実戦で相手のタスキ有無を読むのはプレイヤー側の仕事として残す。
    '', '—', 'きあいのタスキ', 'たべのこし', 'オボンのみ', 'こだわりスカーフ',
    'ひかりのねんど', 'しめったいわ', 'ラムのみ', 'あついいわ', 'さらさらいわ',
    'しろいハーブ', 'メンタルハーブ', 'こうかくレンズ', 'ピントレンズ',
    'せんせいのツメ', 'ひかりのこな', 'でんきだま',
    # メガストーンは「ナイト」で終わる名前で除外されるので個別には並べない
    # （ITEM_JA に日本語名を入れてあるものはそちらで拾われる）。
    'shuca-berry',   # ヤスウのみ。じめん技を1回半減するが、条件付きなので入れない
}


def item_mods(item, m, move_type, type_eff, atk, extra):
    """持ち物によるダメージ補正。(攻撃, その他補正) を返す。
    特性と同じく、自軍の打点にも相手からの被弾にも同じ関数を通すこと。"""
    spec = ITEM_DAMAGE.get(item or '')
    if not spec:
        return atk, extra
    if spec.get('type') and spec['type'] != move_type:
        return atk, extra
    if spec.get('super') and type_eff < 2:
        return atk, extra
    if spec.get('cat') and spec['cat'] != m['cat']:
        return atk, extra
    if spec.get('atk_mult'):
        atk = int(atk * spec['atk_mult'])
    if spec.get('mult'):
        extra *= spec['mult']
    return atk, extra


def offensive_mods(ability, move, m, attacker_types, atk, protean=False,
                   defender_ability=''):
    """攻撃側の特性による補正をまとめて返す。(技タイプ, 威力, 攻撃, その他補正, 一致補正)

    **自軍からの打点も相手からの被弾も、必ずこの関数を通すこと。**
    片方にだけ書くともう片方が抜ける。実際にてきおうりょくが相手側にしか入っておらず、
    自軍がてきおうりょく持ちだと打点が3割以上低く出ていた。

    掛ける段階は my_hit / their_hit と揃えてある。威力と攻撃は基礎ダメージに、
    一致は stab に、残りは extra に入る。順番を変えると乱数判定が1〜2ずれる。
    """
    ability = ability or ''
    move_type, power, extra = m['type'], m['power'], 1.0

    for name, skin_type in SKIN_ABILITIES.items():
        if name in ability and move_type == 'ノーマル':
            move_type, extra = skin_type, extra * 1.2
            break

    # メガソーラー: 実際の天候に関わらず自分の行動だけを にほんばれ 状態として扱う
    if 'メガソーラー' in ability:
        if move == 'ウェザーボール':
            move_type, power = 'ほのお', 100.0
        if move_type == 'ほのお':
            extra *= 1.5
        elif move_type == 'みず':
            extra *= 0.5

    # ほのおのたてがみ: ほのお技の威力1.5倍（メガカエンジシ専用）
    if 'ほのおのたてがみ' in ability and move_type == 'ほのお':
        extra *= 1.5
    # すいほう: 自分のみず技2倍。受けるほのお半減は ability_mod 側
    if 'すいほう' in ability and move_type == 'みず':
        extra *= 2.0
    # フェアリーオーラ: 場に居る間、攻撃側・防御側どちらが持っていてもフェアリー技が1.33倍
    if move_type == 'フェアリー' and ('フェアリーオーラ' in ability
                                  or 'フェアリーオーラ' in (defender_ability or '')):
        extra *= 1.33
    if 'てつのこぶし' in ability and move in PUNCH_MOVES:
        extra *= 1.2
    if 'テクニシャン' in ability and power <= 60:
        power *= 1.5
    if ('ちからもち' in ability or 'ヨガパワー' in ability) and m['cat'] == '物理':
        atk *= 2
    if 'きれあじ' in ability and move in SLASH_MOVES:
        extra *= 1.5
    if 'かたいツメ' in ability and move in CONTACT_MOVES:
        extra *= 1.3

    if protean:
        stab = 1.5              # へんげんじざいが発動した技は必ずタイプ一致
    elif 'てきおうりょく' in ability and move_type in attacker_types:
        stab = 2.0
    else:
        stab = 1.5 if move_type in attacker_types else 1.0
    flags = dict(
        # おやこあい: 1ターンに2回攻撃。2発目は威力1/4。連続技扱いにして damage を2回通す
        parental_bond=('おやこあい' in ability and m['cat'] != '変化' and not m['multi']),
        skill_link=('スキルリンク' in ability),
        acc_mult=(1.3 if 'ふくがん' in ability else 1.0),
    )
    return move_type, power, atk, extra, stab, flags


def _bond_damage(power, atk, dfn, stab, t, extra, crit=False):
    """おやこあいの合計ダメージ。2発目は威力1/4。
    連続技と同じく1発ずつ damage() を通す（発ごとに切り捨てが入るため）。"""
    a = damage(power, atk, dfn, stab, t, extra, crit)
    b = damage(max(1.0, power / 4), atk, dfn, stab, t, extra, crit)
    return a[0] + b[0], a[1] + b[1]


def my_hit(member, move, threat, hp_eff=None):
    """自軍の1技が相手に与えるダメージ。変化技はNone、一撃必殺は別扱い。
    hp_eff は判定・%の分母に使う相手のHP。ステルスロック込みの表を作るときに
    「最大HP - SRダメージ」を渡す。ダメージの実数値（lo/hi）自体は変わらない。"""
    if move in STATUS_MOVES:
        return None
    if move in OHKO_MOVES:
        return dict(move=move, ohko=True, acc=MOVES[move]['acc'])
    m = MOVES[move]
    atk0 = member['st'][1] if m['cat'] == '物理' else member['st'][3]
    # へんげんじざいは場に出て最初の技で発動する。この表は対面した瞬間を見るものなので、
    # 自軍側は発動している前提で計算する（相手側は発動・未発動の2行に分けている）。
    protean = any(k in (member.get('ability') or '') for k in ('へんげんじざい', 'リベロ'))
    move_type, power, atk, extra, stab, flags = offensive_mods(
        member.get('ability'), move, m, member['types'], atk0, protean,
        defender_ability=threat.get('ability'))
    t = move_eff(move, move_type, *threat['types'])
    atk, extra = item_mods(member.get('item'), m, move_type, t, atk, extra)
    am, ab_name = ability_mod(threat['ability'], move_type, member['mold_breaker'],
                              hp_full=(threat['hp_full'] is not False),
                              is_sound=(move in SOUND),
                              is_contact=(move in CONTACT_MOVES))
    if ab_name == 'ハードロック' and t < 2:
        am = 1.0
    disguise = (ab_name == 'ばけのかわ')
    if disguise:
        am = 1.0        # 倍率ではなく1回無効なので、ダメージは等倍のまま
    sturdy = (ab_name == 'がんじょう')
    if sturdy:
        am = 1.0        # がんじょうも倍率ではない。手数を1つ増やす形で効かせる
    dfn = threat['st'][2] if m['cat'] == '物理' else threat['st'][4]
    hp = threat['st'][0] if hp_eff is None else hp_eff

    # タイプ相性か特性で通らない技。damage() は最低1を返すので、そのまま計算すると
    # 「ふゆう持ちにじしんが1ダメージ」のような、実際には起きない数字が出てしまう。
    if t * am == 0:
        return dict(move=move, lo=0, hi=0, pl=0, ph=0, eff=t, verdict='4発+',
                    nullified=True,
                    **({'ab_name': ab_name, 'ab_mult': am} if ab_name else {}))

    # 特性の倍率は「その他補正」に入れる。相性と掛け合わせてから1回で切り捨てると、
    # 段階を分けた場合と結果がずれる（ハードロックの0.75倍で実際にずれる）。
    # 必ず急所に当たる技（トリックフラワーなど）は基礎ダメージが1.5倍になる。
    # 段は damage() の中。威力を1.5倍する形で代用しないこと（+2 の扱いがずれる）
    crit = m['crit']
    if m['multi']:
        lo, hi = multi_damage(m['multi'], power, atk, dfn, stab, t, extra * am,
                              skill_link=flags['skill_link'], crit=crit)
    elif flags['parental_bond']:
        lo, hi = _bond_damage(power, atk, dfn, stab, t, extra * am, crit)
    else:
        lo, hi = damage(power, atk, dfn, stab, t, extra * am, crit)
    # 表示用は「タイプ相性」と「防御特性による補正」を分ける。
    # 両者を掛けた数字だけ出すと、マルチスケイルで半減された2倍が ×1.0 に見えてしまう。
    v = verdict(lo, hi, hp)
    if disguise:
        # 皮で1回止まるぶん、倒すのに必要な手数が1つ増える
        v = verdict_plus_one(v)
    if sturdy and lo >= hp:
        # がんじょうは満タンから必ず1残る。確1のときだけ手数が1つ増える
        v = verdict_plus_one(v)
    result = dict(move=move, lo=lo, hi=hi, pl=round(lo * 100 / hp), ph=round(hi * 100 / hp),
                  eff=t, verdict=v)
    if disguise:
        result['disguise'] = True
    if m['multi']:
        result['hits'] = m['multi']['label']
    if flags['parental_bond']:
        result['hits'] = '2回(おやこあい)'
    if sturdy:
        result['sturdy'] = True
    if crit:
        result['crit'] = True
    if m['pri']:
        result['pri'] = m['pri']
    if am != 1.0 and ab_name:
        result['ab_name'] = ab_name
        result['ab_mult'] = am
    acc = m['acc'] and min(100.0, m['acc'] * flags['acc_mult'])
    if acc and acc < 100:
        result['acc'] = round(acc)
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
    defender_sturdy = False
    for mv, usage in threat['moves_use'][:8]:
        m = MOVES.get(mv)
        if not m or not m['power']:
            continue
        atk0 = threat['st'][1] if m['cat'] == '物理' else threat['st'][3]
        move_type, power, atk, extra, stab, flags = offensive_mods(
            ability, mv, m, threat['types'], atk0, threat['protean'],
            defender_ability=(member.get('ability') if defender_ability_on else ''))

        t = move_eff(mv, move_type, *member['types'])
        atk, extra = item_mods(threat['item'], m, move_type, t, atk, extra)

        # 自軍の防御特性。あついしぼう・ふゆう・マルチスケイルなどが効く。
        # ばけのかわは倍率ではないのでここでは触らず、呼び出し側で扱う。
        am = 1.0
        if defender_ability_on:
            am, ab_name = ability_mod(member.get('ability'), move_type, mold,
                                      hp_full=True, is_sound=(mv in SOUND),
                                      is_contact=(mv in CONTACT_MOVES))
            if ab_name == 'ハードロック' and t < 2:
                am = 1.0
            if ab_name in ('ばけのかわ', 'がんじょう'):
                am = 1.0
                if ab_name == 'がんじょう':
                    defender_sturdy = True

        if t * am == 0:
            continue    # タイプ相性か特性で通らない技。damage() は最低1を返すので、
                        # ここで落とさないと「じしん 1%」が主表示になってしまう
        dfn = member['st'][2] if m['cat'] == '物理' else member['st'][4]
        # 特性の倍率は my_hit と同じく「その他補正」に入れる（相性とは段階を分ける）
        if m['multi']:
            lo, hi = multi_damage(m['multi'], power, atk, dfn, stab, t, extra * am,
                                  skill_link=flags['skill_link'], crit=m['crit'])
        elif flags['parental_bond']:
            lo, hi = _bond_damage(power, atk, dfn, stab, t, extra * am, m['crit'])
        else:
            lo, hi = damage(power, atk, dfn, stab, t, extra * am, m['crit'])
        cand = dict(move=mv, lo=lo, hi=hi, usage=usage,
                    pl=round(lo * 100 / member['st'][0]),
                    ph=round(hi * 100 / member['st'][0]))
        if m['multi']:
            cand['hits'] = m['multi']['label']
        if flags['parental_bond']:
            cand['hits'] = '2回(おやこあい)'
        if m['crit']:
            cand['crit'] = True
        if m['pri']:
            cand['pri'] = m['pri']
        (main if usage > RARE_MOVE_THRESHOLD else rare).append(cand)

    # 主表示は採用率が閾値を超える技の中での最大打点。低採用の技しか無いポケモンだけ、
    # 仕方なくそちらを使う（何も出ないと被弾が空欄になってしまうため）。
    pool = main or rare
    if not pool:
        return dict(move='—', lo=0, hi=0, pl=0, ph=0)
    if defender_sturdy:
        # がんじょう: 満タンから受けるぶんは必ず1残る。呼び出し側が手数+1にする
        for c in pool:
            c['sturdy'] = True
    best = max(pool, key=lambda x: x['hi'])
    # 先制技で落とされるなら、素早さで勝っていても行動前に倒される。
    # 他にもっとダメージの大きい技があっても、こちらを主表示にする。
    ko = [c for c in pool if c.get('pri', 0) > 0 and c['hi'] >= member['st'][0]]
    if ko and best.get('pri', 0) <= 0:
        best = max(ko, key=lambda x: x['hi'])
    # 低採用の技が主要技を上回るときだけ、補足として持たせる
    if main and rare:
        top_rare = max(rare, key=lambda x: x['hi'])
        if top_rare['hi'] > best['hi']:
            best = dict(best, rare=top_rare)
    return best


# ---------------------------------------------------------------- 処理判定
# 「処理できる」の定義（ユーザー指定）:
#   ① 先手（素早さ上、または先制技）を取っており、1発で倒せる
#   ② 後手だが、相手の最大打点を耐えて倒せる
#   ③ 先手後手に関わらず、ターン制の打ち合いで先に相手を倒せる
# ①②は③の特殊ケースなので、実装は③のレースに一本化してある。
# 乱数はこちらに不利な側で固定する（自分は最低乱数、相手は最高乱数）。
# そうしないと「高乱数を引けば勝てる」相手まで処理できる扱いになってしまう。

RECOVERY_MOVES = {'なまける', 'じこさいせい', 'はねやすめ', 'こうごうせい',
                  'つきのひかり', 'あさのひざし', 'ミルクのみ', 'タマゴうみ',
                  'ねむる', 'ねがいごと'}
MAX_TURNS = 12

# 「超有利」の線引き。処理できる中でもとくに安心して投げられる対面を選び出すためのもので、
# **処理できるかどうかの判定そのものには一切関わらない**（表示に★を付けるだけ）。
#   ・先手を取って1発 … 相手に行動させない
#   ・1発だが後手 … 返しが最大乱数でもこの%以下なら、素早さを読み違えても崩れない
SUPER_TAKE_PH = 40


def _heal_parts(mon, moves_use=None):
    """(回復技1回ぶんの回復量, たべのこしの毎ターン回復量) を返す。
    回復技はそのターン攻撃できない。たべのこしはターンを消費しない。"""
    hp = mon['st'][0]
    if moves_use is None:
        names = set(mon.get('moves') or [])
    else:
        names = {mv for mv, u in moves_use if u > RARE_MOVE_THRESHOLD}
    move_heal = hp // 2 if (names & RECOVERY_MOVES) else 0
    passive = hp // 16 if 'たべのこし' in (mon.get('item') or '') else 0
    return move_heal, passive


def _turns_to_ko(hp, first_dmg, rest_dmg, extra_turns=0):
    """1発目 first_dmg、2発目以降 rest_dmg で倒すのに要するターン数。倒せないなら None。
    マルチスケイルのように満タンのときだけ効く特性があるので、初撃を分けている。"""
    left = hp - first_dmg
    if left <= 0:
        return 1 + extra_turns
    if rest_dmg <= 0:
        return None
    n = 1 + -(-left // rest_dmg) + extra_turns
    return n if n <= MAX_TURNS else None


def _sustain_cycle(hp_heal, passive, incoming):
    """回復技を挟みながら生き残れるか。
    n ターンに1回だけ回復技を使い、残り n-1 ターン攻撃できる、その n を返す。
    回復技だけでは支えきれないなら None、そもそも削られないなら 0（毎ターン攻撃可）。"""
    net = incoming - passive
    if net <= 0:
        return 0                      # たべのこしだけで足りる。回復技は要らない
    if hp_heal <= 0:
        return None
    n = hp_heal // net + 1            # 1回の回復で net×(n-1) 分を取り戻せる
    return n if n >= 2 else None      # n=1 は「毎ターン回復＝攻撃できない」ので支えられない


def process_check(member, threat):
    """この駒がこの相手を処理できるか。(できるか, 理由, 内訳) を返す。

    内訳は表示用の材料（手数・先手かどうか・被弾%・超有利か）で、判定には使わない。
    3つ目を足す前から `ok, why = ...` で受けている呼び出しがあるので、
    受け取り方を変えるときは build/matchup.py も一緒に直すこと。

    回復技はそのターン攻撃できない。これを踏まえると相手の最適行動は二択になる:
      ・回復量 >= こちらの打点 なら、毎ターン回復すれば永久に落ちない → 処理不可
      ・回復量 < こちらの打点 なら、回復するほど攻撃ターンを失って損 → 一度も回復しない
    なので相手側は「回復し続けて詰む」か「まったく回復しない」かのどちらかで足りる。
    """
    back = their_hit(threat, member)
    their_dmg = back['hi']                     # 相手は最高乱数
    their_pri = back.get('pri', 0) or 0
    my_hp, their_hp = member['st'][0], threat['st'][0]
    my_heal, my_pass = _heal_parts(member)
    their_heal, their_pass = _heal_parts(threat, threat['moves_use'])

    # 2発目以降は相手が満タンではない。マルチスケイル・がんじょうは初撃にしか効かない
    threat_hurt = dict(threat, hp_full=False)

    best = None
    for mv in member['moves']:
        h = my_hit(member, mv, threat)
        if not h or h.get('ohko') or not h.get('hi'):
            continue                           # 一撃必殺は運任せなので数えない
        h2 = my_hit(member, mv, threat_hurt) or h
        first_dmg = h['lo']                    # 自分は最低乱数
        rest_dmg = h2['lo']                    # 2発目以降（満タン依存の特性が切れた後）
        # 相手が回復技を撃ち続けて耐えきれるなら、この技では永久に落とせない。
        # 回復されると満タンに戻りうるので、判定には初撃ぶんの打点を使う
        if their_heal and their_heal + their_pass >= first_dmg:
            continue
        extra = 1 if (h.get('sturdy') or h.get('disguise')) else 0
        my_turns = _turns_to_ko(their_hp, first_dmg - their_pass,
                                rest_dmg - their_pass, extra)
        if my_turns is None:
            continue
        if mv in DRAWBACK_MOVES:
            my_turns = my_turns * 2 - 1        # 反動で次のターン動けない
        # こちらが回復技を挟んで支えられるか。挟むぶん攻撃ターンが減る
        cycle = _sustain_cycle(my_heal, my_pass, their_dmg)
        if cycle == 0:
            their_turns = None                 # そもそも削られない
        elif cycle:
            their_turns = None
            my_turns = -(-my_turns * cycle // (cycle - 1))   # n ターンに1回は回復に使う
            if my_turns > MAX_TURNS:
                continue
        else:
            their_turns = _turns_to_ko(my_hp, their_dmg - my_pass,
                                       their_dmg - my_pass)
        pri = h.get('pri', 0) or 0
        first = (pri, member['speed']) > (their_pri, threat['speed'])
        if their_turns is None:
            ok = True
        elif first:
            ok = my_turns <= their_turns
        else:
            ok = my_turns < their_turns
        if ok:
            why = ('先手1発' if first and my_turns == 1 else
                   '後手だが耐えて1発' if my_turns == 1 else
                   f'打ち合い{my_turns}ターン')
            if best is None or my_turns < best[0]:
                best = (my_turns, mv, why, first)
    take_ph = back['ph']
    if best:
        # 超有利かどうかは「1発で倒せる」ことが前提。そのうえで先手を取っているか、
        # 後手でも返しが軽いか。SUPER_TAKE_PH の意味は定義のところに書いてある
        info = dict(turns=best[0], first=best[3], take_ph=take_ph,
                    super=best[0] == 1 and (best[3] or take_ph <= SUPER_TAKE_PH))
        return True, f"{best[1]}（{best[2]}）", info
    return False, '', dict(turns=None, first=False, take_ph=take_ph, super=False)


def choose_move(hits):
    """主表示する技と、次善の技を選ぶ。
    判定が最も良い技を主にする。同じ確1なら**先制技を優先する** —
    素早さに関係なく先に倒せるので、同じ確1でも価値が違う。
    そのうえで同条件ならデメリットのない技（はかいこうせん以外）を優先する。"""
    attacks = [h for h in hits if h and not h.get('ohko')]
    if not attacks:
        return None, None

    def key(m):
        first = m['verdict'] == '確1' and m.get('pri', 0) > 0
        return (-VERDICT_RANK.get(m['verdict'], 0),
                0 if first else 1,
                m['move'] in DRAWBACK_MOVES, -m['lo'])

    attacks = sorted(attacks, key=key)
    primary = attacks[0]
    alt = None
    for m in attacks[1:]:
        if (m['verdict'] != primary['verdict']
                or m['move'] in DRAWBACK_MOVES or primary['move'] in DRAWBACK_MOVES):
            alt = m
            break
    return primary, alt


def build_members(party=None):
    """party.py の定義から実数値つきのメンバーリストを作る。
    party を渡すと、party.txt ではなくそのリストから作る（別案の検討に使う）。"""
    out = []
    for p in (PARTY if party is None else party):
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


def verify_party_code():
    """party.txt を文字列コードにして戻し、同じパーティになるか確かめる。

    符号化は台帳（data/code_dict.json）のインデックスに依っているので、
    台帳と図鑑・技がずれると黙って別のポケモンになる。ここで止める。
    台帳の追記は build/export_app_data.py が行うので、こちらは読むだけ。"""
    import partycode
    reg, added = partycode.sync_registry(write=False)
    if added:
        raise SystemExit(
            '文字列コードの台帳（data/code_dict.json）が古いです。\n'
            '  未登録: ' + '、'.join(f'{k} {len(v)}件' for k, v in added.items()) + '\n'
            '  python build/export_app_data.py を実行して台帳を更新してください。')
    code = partycode.encode(PARTY)
    back = partycode.decode(code)
    got = _parse_party_text(back)
    want = [(p['name'], p['form'], p['item'], p['ability'],
             p['nature'], tuple(p['ev']), tuple(p['moves'])) for p in PARTY]
    if got != want:
        raise SystemExit('文字列コードの往復でパーティが変わりました。\n'
                         f'  元: {want}\n  戻り: {got}')
    return code


def _parse_party_text(text):
    from party import _parse_party
    return [(p['name'], p['form'], p['item'], p['ability'],
             p['nature'], tuple(p['ev']), tuple(p['moves'])) for p in _parse_party(text)]


def main():
    """データの整合性を確かめる。以前はここで index.html を書き出していたが、
    表示はブラウザ側（assets/app.js）に移したので、生成物は作らない。
    パーティの実数値検証・図鑑や技の欠落・特性の未分類は、build_threats() と
    verify() の中でチェックしてエラーや警告を出す。
    ブラウザが読む JSON は build/export_app_data.py が書き出す。"""
    members = build_members()
    verify(members)
    threats = build_threats()
    code = verify_party_code()
    print('検証完了')
    print(f'  相手 {len(threats)} 行 / 味方 {len(members)} 体')
    print(f'  パーティの文字列コード {len(code)} 文字（往復一致）')
    print('  ブラウザ用データを作るには: python build/export_app_data.py')


if __name__ == '__main__':
    main()
