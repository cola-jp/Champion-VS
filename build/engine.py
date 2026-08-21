"""
ポケモンチャンピオンズ 対面ダメージ計算エンジン

データソース（すべてテキスト。Excel は要らない）:
  data/dex.csv               ... 図鑑。種族値・タイプ・特性
  data/moves.csv             ... 技データ
  data/type_chart.csv        ... タイプ相性表
  data/技使用率データ.JSON     ... 使用率・性格・努力値配分・持ち物・特性・技（英語名、月替わり）
  data/move_names_en_ja.json ... 技使用率データ.JSON の英語技名 → 日本語技名の対応表
  data/abilities_ja.json     ... 特性名 → 効果の対応表（build/extract_abilities.py で生成）

data/ポケモン図鑑.xlsx は移行元として残してあるが、コードはもう読まない。
新しいポケモンや技は CSV を直接編集して足す（差分が見えるので取り込みミスに気づける）。

レギュレーションM-B シングル / レベル50固定 / 個体値31 / 努力値は「能力ポイント」表記
  1ポイント = 努力値8 / 1体あたり合計66ポイントまで / 1ステータス最大32ポイント
"""
import csv
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DEX_CSV = os.path.join(DATA, 'dex.csv')
MOVES_CSV = os.path.join(DATA, 'moves.csv')
TYPE_CHART_CSV = os.path.join(DATA, 'type_chart.csv')
JSON_PATH = os.path.join(DATA, '技使用率データ.JSON')
MOVE_NAME_JSON_PATH = os.path.join(DATA, 'move_names_en_ja.json')
ABILITY_JSON_PATH = os.path.join(DATA, 'abilities_ja.json')


def _read_csv(path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


class PokemonNotFoundError(Exception):
    """使用率データの pokemon_id が図鑑（data/dex.csv）に存在しない。"""


class RegionFormError(Exception):
    """region_form に対応する図鑑エントリが見つからない。"""

# ---------------------------------------------------------------- データ読み込み

# タイプ相性表: EFF[(攻撃タイプ, 防御タイプ)] = 倍率
EFF = {}
for _r in _read_csv(TYPE_CHART_CSV):
    _atk = _r['attack']
    for _dt, _v in _r.items():
        if _dt != 'attack' and _v != '':
            EFF[(_atk, _dt)] = float(_v)

# 図鑑側の技名の誤りを読み込み時に直す。英語名をそのまま音写してしまっているもの。
# 本来は data/moves.csv を直すのが筋だが、使用率データ側とも揃える必要があるのでここで吸収する。
MOVE_NAME_FIX = {
    'スピリットブレイク': 'ソウルクラッシュ',   # Spirit Break の正式和名はソウルクラッシュ
    'うでずもう': 'アームハンマー',             # Hammer Arm の正式和名はアームハンマー
}


def fix_move_name(name):
    return MOVE_NAME_FIX.get(name, name)


# ランク変化欄の書式: '自分こうげき+2/とくこう+2' '相手ぼうぎょ-1(30%)'
# 2つ目以降は「自分/相手」を省略して直前を引き継ぐ。
# 末尾の括弧は発動条件（確率・接触時など）で、付いていると確実には発動しない。
RANK_STAT = {'こうげき': 'atk', 'ぼうぎょ': 'def', 'とくこう': 'spa',
             'とくぼう': 'spd', 'すばやさ': 'spe', '全能力': 'all'}
_RANK_RE = re.compile(r'^(自分|相手)?(.+?)([+\-]\d+)(?:\((.+)\))?$')


def parse_rank_change(text):
    """ランク変化欄を [{target, stat, stages, cond}] にする。読めない書式は捨てる。"""
    out = []
    target = '自分'
    for part in (text or '').split('/'):
        part = part.strip()
        if not part:
            continue
        m = _RANK_RE.match(part)
        if not m:
            continue
        if m.group(1):
            target = m.group(1)
        stat = RANK_STAT.get(m.group(2))
        if not stat:
            continue
        out.append(dict(target=target, stat=stat,
                        stages=int(m.group(3)), cond=m.group(4) or None))
    return out


# 連続技。効果欄の「2〜5回連続攻撃」「3回連続攻撃」から導く。
# トリプルアクセルのように「当たるごとに威力が20ずつ増加」するものは step に増分を入れる。
_MULTI_RE = re.compile(r'(\d+)(?:〜(\d+))?回連続攻撃')
_STEP_RE = re.compile(r'威力が(\d+)ずつ増加')


def parse_multi_hit(effect, power):
    """連続技なら {min, max, step, label} を返す。単発なら None。"""
    if not effect:
        return None
    m = _MULTI_RE.search(effect)
    if not m or not power:
        return None
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    s = _STEP_RE.search(effect)
    return dict(min=lo, max=hi, step=int(s.group(1)) if s else 0,
                label=f'{lo}〜{hi}回' if hi != lo else f'{lo}回')


def multi_damage(mh, power, attack, defense, stab=1.0, type_eff=1.0, extra=1.0):
    """連続技の合計ダメージ。(最低回数×最低乱数, 最高回数×最高乱数) を返す。
    1発ずつ damage() を通して足すこと。各発で切り捨てが入るので、
    威力を合算してから1回で計算すると数値が合わない。"""
    def total(hits, idx):
        return sum(damage(power + mh['step'] * i, attack, defense,
                          stab, type_eff, extra)[idx]
                   for i in range(hits))
    return total(mh['min'], 0), total(mh['max'], 1)


# 技データ: MOVES[技名] = {type, cat, power, acc, pri, effect, ranks, ohko}
MOVES = {}
for _r in _read_csv(MOVES_CSV):
    if not _r['name']:
        continue
    _effect = _r['effect'] or None
    MOVES[fix_move_name(_r['name'])] = dict(
        type=_r['type'], cat=_r['category'],
        power=float(_r['power']) if _r['power'] else 0,
        acc=float(_r['accuracy']) if _r['accuracy'] else None,
        pri=float(_r['priority']) if _r['priority'] else 0.0,
        effect=_effect,
        ranks=parse_rank_change(_r.get('rank_change')),
        # 一撃必殺・連続技は技名を並べるのではなく効果欄から拾う。
        # 新しい技が増えても、効果欄に同じ書き方をしてあれば勝手に効く。
        ohko=bool(_effect and '一撃必殺' in _effect),
        multi=parse_multi_hit(_effect, float(_r['power']) if _r['power'] else 0))


def self_boost(move):
    """その技を1回使うと自分の攻撃系ランクが何段階上がるか。{'atk': 2} のように返す。
    条件付き（確率・接触時など）は確実に積めないので数えない。
    ダメージ表の「積み技+n」はこれを見て決める。"""
    m = MOVES.get(move)
    if not m or m['cat'] != '変化':
        return {}
    out = {}
    for r in m['ranks']:
        if r['target'] != '自分' or r['cond'] or r['stages'] <= 0:
            continue
        for s in (('atk', 'spa') if r['stat'] == 'all' else (r['stat'],)):
            if s in ('atk', 'spa'):
                out[s] = max(out.get(s, 0), r['stages'])
    return out


def rank_multiplier(stages):
    """ランク補正の倍率。+n は (2+n)/2、-n は 2/(2+n)。"""
    return (2 + stages) / 2 if stages >= 0 else 2 / (2 - stages)

# 図鑑: DEX[ポケモン名] = {t1, t2, ab, ab_list, base}
# メガ形態やリージョンフォームは「メガ○○」「○○(ヒスイ)」で別エントリ。
# ab_list が特性の正しい一覧。ab は互換のために連結した文字列で、
# 既存の部分一致（'あついしぼう' in ab）がそのまま動くように残してある。
DEX = {}
BY_DEX_NO = {}   # 図鑑番号 -> [通常形態名, メガ形態名, ...]
for _r in _read_csv(DEX_CSV):
    if not _r['name']:
        continue
    _abs = [a for a in (_r['abilities'] or '').split('/') if a]
    DEX[_r['name']] = dict(
        t1=_r['type1'], t2=_r['type2'] or None,
        ab=''.join(_abs), ab_list=_abs,
        base=[int(_r[k]) for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')])
    try:
        BY_DEX_NO.setdefault(int(_r['no']), []).append(_r['name'])
    except (ValueError, TypeError):
        pass


def _check_dex():
    """dex.csv / moves.csv の打ち間違いを、分かりやすい形で早めに知らせる。
    新しいポケモンや技を手で足したときの取りこぼしを拾うのが目的。
    タイプ名は相性表に無ければ計算時に KeyError になるだけで原因が分からないので、
    ここで名前を挙げて止める。"""
    types = {a for a, _ in EFF} | {d for _, d in EFF}
    bad = []
    for name, d in DEX.items():
        for t in (d['t1'], d['t2']):
            if t and t not in types:
                bad.append(f'  {name}: タイプ「{t}」は相性表にありません')
        if len(d['base']) != 6 or any(v <= 0 for v in d['base']):
            bad.append(f'  {name}: 種族値がおかしいです {d["base"]}')
        if not d['ab_list']:
            bad.append(f'  {name}: 特性が空です')
    for name, m in MOVES.items():
        if m['type'] not in types:
            bad.append(f'  技 {name}: タイプ「{m["type"]}」は相性表にありません')
        if m['cat'] not in ('物理', '特殊', '変化'):
            bad.append(f'  技 {name}: 分類「{m["cat"]}」は 物理/特殊/変化 のいずれかにしてください')
    if bad:
        print('data/dex.csv または data/moves.csv の内容に問題があります:')
        print('\n'.join(bad))
        raise SystemExit(1)


_check_dex()

# 技名の英語→日本語対応表（一次情報）。技使用率データ.JSON の技は英語名で入っているので、
# 月が変わってもこれを差し替える必要はない。ここに無い技は警告を出して英語名のまま残す。
MOVE_NAME_EN_JA = json.load(open(MOVE_NAME_JSON_PATH, encoding='utf-8'))

# 特性名 → 効果。ダメージ計算そのものには使わず、「この特性を計算に入れなくてよいか」を
# 人が判断するための参照データ。generate.py の ABILITY_HANDLING と突き合わせて、
# 未分類の特性が使用率データに出てきたら警告する。
ABILITIES = json.load(open(ABILITY_JSON_PATH, encoding='utf-8'))

# 使用率JSON（英語名・230体）
USAGE = json.load(open(JSON_PATH, encoding='utf-8'))

# JSONの region_form を図鑑側の日本語表記に対応させるためのキーワード。
# 例: 'samurott-hisui' -> 'ヒスイ' -> 図鑑の 'ダイケンキ(ヒスイ)'
#     'rotom-wash'     -> 'ウォッシュ' -> 図鑑の 'ウォッシュロトム'
# これを見ずに図鑑番号の先頭を取ると、ヒスイダイケンキが通常ダイケンキの種族値で計算される。
REGION_KEYWORD = {
    'alola': 'アローラ', 'hisui': 'ヒスイ', 'galar': 'ガラル',
    'wash': 'ウォッシュ', 'heat': 'ヒート', 'frost': 'フロスト',
    'fan': 'スピン', 'mow': 'カット', 'eternal': 'えいえん',
    'female': '♀', 'dusk': 'たそがれ', 'midnight': 'まよなか', 'midday': 'まひる',
    'paldea-combat': 'パルデア単', 'paldea-blaze': 'パルデア炎', 'paldea-aqua': 'パルデア水',
}
REGION_ANY = ('アローラ', 'ヒスイ', 'ガラル', 'パルデア', 'ウォッシュ', 'ヒート',
              'フロスト', 'スピン', 'カット', 'えいえん', 'たそがれ', 'まよなか', 'まひる')


# メガ形態の判定。「名前がメガで始まるか」で見ると、メガニウム・メガヤンマのように
# たまたま名前がメガで始まる普通のポケモンをメガ形態と誤判定する。
# 実際にメガニウムがメガメガニウムの代わりに使われ、種族値もタイプ（フェアリー）も
# 間違ったまま表に出ていた。同じ図鑑番号の中に「メガ」を外した名前が居るときだけ
# メガ形態とみなす。メガリザードンX のように末尾にX/Yが付く形態も拾う。
def _plain_key(name):
    """形態の括弧書きを外した名前。'フラエッテ(えいえん)' -> 'フラエッテ'。
    メガフラエッテの元が括弧付きでしか載っていないので、これを外さないと対応が取れない。"""
    return re.sub(r'[(（].*$', '', name)


MEGA_NAMES = set()
for _names in BY_DEX_NO.values():
    for _n in _names:
        if not _n.startswith('メガ'):
            continue
        _rest = _n[2:]
        if _rest[-1:] in ('X', 'Y'):        # メガリザードンX / Y
            _rest = _rest[:-1]
        if any(_plain_key(_o) == _rest for _o in _names if _o != _n):
            MEGA_NAMES.add(_n)


def is_mega(name):
    """メガ形態かどうか。name.startswith('メガ') を直接使わないこと。"""
    return name in MEGA_NAMES


# リージョンフォームにメガを紐付ける例外。
# フラエッテは図鑑に「フラエッテ(えいえん)」しか無く、メガフラエッテはその形態のメガ。
# 一方ライチュウ(アローラ)やヤドラン(ガラル)は通常形態が別に居て、メガはそちらのものなので、
# 「リージョンフォームにメガを付ける」を一般ルールにすると誤ってメガを生やしてしまう。
# 実際に該当するのはこの1件だけなので、一般化せず例外として書く。
REGION_FORM_MEGA = {'フラエッテ(えいえん)': 'メガフラエッテ'}


def resolve_form(entry, want_mega=False):
    """JSONの1エントリから、図鑑上の正しいポケモン名を返す。
    region_form を無視すると別形態の種族値で計算してしまうので必ずこれを通すこと。
    pokemon_id が図鑑に無ければ PokemonNotFoundError、region_form が指定されているのに
    対応する図鑑エントリが無ければ RegionFormError を投げる。どちらも黙って別形態の
    種族値で計算しないための安全弁（過去にヒスイダイケンキを通常種で計算したバグがある）。"""
    names = BY_DEX_NO.get(entry['pokemon_id'], [])
    if not names:
        raise PokemonNotFoundError(str(entry['pokemon_id']))
    rf = entry.get('region_form') or ''
    # 'paldea-combat-breed' のような複合キーは長いものから先に照合する
    keyword = None
    for k in sorted(REGION_KEYWORD, key=len, reverse=True):
        if k in rf:
            keyword = REGION_KEYWORD[k]
            break
    if keyword:
        cands = [n for n in names if keyword in n]
        if not cands:
            raise RegionFormError(f"pokemon_id={entry['pokemon_id']} region_form={rf!r}")
    else:
        cands = [n for n in names if not any(r in n for r in REGION_ANY)]
        # ♂♀で分かれている種は、region_formが無い側を♂とみなす
        if not cands:
            cands = names
        elif len(cands) > 1 and any('♂' in n for n in cands):
            cands = [n for n in cands if '♀' not in n]
    if not cands:
        cands = names
    megas = [n for n in cands if is_mega(n)]
    plains = [n for n in cands if not is_mega(n)]
    if not megas:
        # リージョンフォーム名で絞ると、その形態のメガ（メガフラエッテ）が候補から外れる。
        # 上の REGION_FORM_MEGA に書いた組み合わせだけ拾い直す。
        for _c in cands:
            _m = REGION_FORM_MEGA.get(_c)
            if _m and _m in names:
                megas = [_m]
                break
    if want_mega and megas:
        return megas[0], megas
    return (plains[0] if plains else cands[0]), megas

# ---------------------------------------------------------------- 実数値の計算

NATURE = {
    'lonely': ('atk', 'def'), 'brave': ('atk', 'spe'), 'adamant': ('atk', 'spa'),
    'naughty': ('atk', 'spd'), 'bold': ('def', 'atk'), 'relaxed': ('def', 'spe'),
    'impish': ('def', 'spa'), 'lax': ('def', 'spd'), 'timid': ('spe', 'atk'),
    'hasty': ('spe', 'def'), 'jolly': ('spe', 'spa'), 'naive': ('spe', 'spd'),
    'modest': ('spa', 'atk'), 'mild': ('spa', 'def'), 'quiet': ('spa', 'spe'),
    'rash': ('spa', 'spd'), 'calm': ('spd', 'atk'), 'gentle': ('spd', 'def'),
    'sassy': ('spd', 'spe'), 'careful': ('spd', 'spa'),
}
IDX = {'hp': 0, 'atk': 1, 'def': 2, 'spa': 3, 'spd': 4, 'spe': 5}
NAT_JA = {
    'adamant': 'いじっぱり', 'jolly': 'ようき', 'timid': 'おくびょう', 'modest': 'ひかえめ',
    'bold': 'ずぶとい', 'impish': 'わんぱく', 'calm': 'おだやか', 'careful': 'しんちょう',
    'naive': 'むじゃき', 'hasty': 'せっかち', 'lonely': 'さみしがり', 'brave': 'ゆうかん',
    'naughty': 'やんちゃ', 'relaxed': 'のんき', 'lax': 'のうてんき', 'mild': 'おっとり',
    'quiet': 'れいせい', 'rash': 'うっかりや', 'gentle': 'おとなしい', 'sassy': 'なまいき',
}


def stats(base, ev_points, nature=None):
    """種族値と能力ポイント(6要素)から実数値を返す。レベル50・個体値31固定。"""
    out = []
    for i in range(6):
        ev = ev_points[i] * 8
        if i == 0:
            out.append(int((2 * base[0] + 31 + ev // 4) * 50 // 100) + 60)
        else:
            out.append(int((2 * base[i] + 31 + ev // 4) * 50 // 100) + 5)
    if nature in NATURE:
        up, dn = NATURE[nature]
        out[IDX[up]] = int(out[IDX[up]] * 1.1)
        out[IDX[dn]] = int(out[IDX[dn]] * 0.9)
    return out


# ---------------------------------------------------------------- タイプ相性と特性

def eff(move_type, t1, t2=None):
    """タイプ相性倍率。t2 は None 可。"""
    e = EFF[(move_type, t1)]
    if t2:
        e *= EFF[(move_type, t2)]
    return e


# 防御側の特性による軽減・無効（日本語名と英語名の両方を受け付ける）
IMMUNE_JA = {'ふゆう': 'じめん', 'もらいび': 'ほのお', 'ちょすい': 'みず', 'よびみず': 'みず',
             'かんそうはだ': 'みず', 'ちくでん': 'でんき', 'ひらいしん': 'でんき',
             'でんきエンジン': 'でんき', 'そうしょく': 'くさ'}
IMMUNE_EN = {'levitate': 'じめん', 'flash-fire': 'ほのお', 'water-absorb': 'みず',
             'storm-drain': 'みず', 'dry-skin': 'みず', 'volt-absorb': 'でんき',
             'lightning-rod': 'でんき', 'motor-drive': 'でんき', 'sap-sipper': 'くさ',
             'earth-eater': 'じめん'}
HALF_JA = {'あついしぼう': ('ほのお', 'こおり'), 'たいねつ': ('ほのお',), 'すいほう': ('ほのお',)}
HALF_EN = {'thick-fat': ('ほのお', 'こおり'), 'heatproof': ('ほのお',), 'water-bubble': ('ほのお',)}
# ability_mod が返す特性名を表示用の日本語に揃える
ABILITY_DISPLAY = {
    'levitate': 'ふゆう', 'flash-fire': 'もらいび', 'water-absorb': 'ちょすい',
    'storm-drain': 'よびみず', 'dry-skin': 'かんそうはだ', 'volt-absorb': 'ちくでん',
    'lightning-rod': 'ひらいしん', 'motor-drive': 'でんきエンジン', 'sap-sipper': 'そうしょく',
    'earth-eater': '土食い', 'thick-fat': 'あついしぼう', 'heatproof': 'たいねつ',
    'water-bubble': 'すいほう',
}
SOUND = {'ハイパーボイス', 'うたかたのアリア', 'ばくおんぱ', 'いびき', 'エコーボイス', 'りんしょう'}


def ability_mod(ability, move_type, mold_breaker=False, hp_full=True, is_sound=False):
    """防御側特性による倍率と、発動した特性名を返す。
    mold_breaker=True（かたやぶり）なら防御特性を全て無視する。
    ばけのかわは倍率ではなく「1回無効」なのでここでは 1.0 を返し、呼び出し側でターン数に加算する。
    """
    ab = ability or ''
    if mold_breaker:
        return 1.0, ''
    for table in (IMMUNE_JA, IMMUNE_EN):
        for name, typ in table.items():
            if name in ab and typ == move_type:
                return 0.0, ABILITY_DISPLAY.get(name, name)
    for table in (HALF_JA, HALF_EN):
        for name, types in table.items():
            if name in ab and move_type in types:
                return 0.5, ABILITY_DISPLAY.get(name, name)
    if ('マルチスケイル' in ab or 'multiscale' in ab) and hp_full:
        return 0.5, 'マルチスケイル'
    if ('ぼうおん' in ab or 'soundproof' in ab) and is_sound:
        return 0.0, 'ぼうおん'
    if any(k in ab for k in ('ハードロック', 'フィルター', 'solid-rock', 'filter', 'prism-armor')):
        return 0.75, 'ハードロック'   # ※効果抜群のときのみ有効。呼び出し側で判定すること
    if 'ばけのかわ' in ab or 'disguise' in ab:
        return 1.0, 'ばけのかわ'
    return 1.0, ''


# ---------------------------------------------------------------- ダメージ計算

def damage(power, attack, defense, stab=1.0, type_eff=1.0, extra=1.0):
    """レベル50固定のダメージ計算。(最低乱数, 最高乱数) を返す。
    stab   : タイプ一致補正（通常1.5 / てきおうりょく2.0）
    type_eff: タイプ相性 × 防御特性の倍率
    extra  : その他の乗算補正（いのちのたま1.3 / きれあじ1.5 / フェアリースキン1.2 など）
    丸めは 基礎 → 乱数 → 一致 → 相性 → その他 の順に切り捨てる。
    """
    base = int(int(2 * 50 / 5 + 2) * power * attack / defense / 50) + 2

    def roll(r):
        x = int(base * r)
        x = int(x * stab)
        x = int(x * type_eff)
        x = int(x * extra)
        return max(1, x)

    return roll(0.85), roll(1.0)


def verdict(lo, hi, hp):
    """最低乱数・最高乱数・相手HPから確定何発かを返す。"""
    if lo >= hp:
        return '確1'
    if hi >= hp:
        return '乱1'
    if lo * 2 >= hp:
        return '確2'
    if hi * 2 >= hp:
        return '乱2'
    if lo * 3 >= hp:
        return '確3'
    return '4発+'


VERDICT_RANK = {'確1': 5, '乱1': 4, '確2': 3, '乱2': 2, '確3': 1, '4発+': 0}

# ばけのかわで1回無効化されるぶん、必要な手数が1つ増えたときの判定。
# 乱2 に1発足すと「3発だが乱数」で、この目盛りには無い。控えめに 4発+ に寄せる。
VERDICT_PLUS_ONE = {'確1': '確2', '乱1': '乱2', '確2': '確3',
                    '乱2': '4発+', '確3': '4発+', '4発+': '4発+'}


def verdict_plus_one(v):
    return VERDICT_PLUS_ONE.get(v, v)


# 条件で剥がれる防御特性。剥がれた後のダメージも併記する対象。
STRIPPABLE_ABILITIES = ('マルチスケイル', 'ばけのかわ')
