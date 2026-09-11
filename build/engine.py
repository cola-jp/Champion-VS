"""
ポケモンチャンピオンズ 対面ダメージ計算エンジン

データソース（すべてテキスト。Excel は要らない）:
  data/dex.csv               ... 図鑑。種族値・タイプ・特性
  data/moves.csv             ... 技データ
  data/type_chart.csv        ... タイプ相性表
  data/usage.json            ... 使用率・性格・能力ポイント配分・持ち物・特性・技（日本語、月替わり）
  data/move_names_en_ja.json ... 旧データ（英語名）用の技名対応表。新ソースでは使わない
  data/abilities_ja.json     ... 特性名 → 効果の対応表（build/extract_abilities.py で生成）

data/ポケモン図鑑.xlsx は移行元として残してあるが、コードはもう読まない。
新しいポケモンや技は CSV を直接編集して足す（差分が見えるので取り込みミスに気づける）。

レギュレーションM-C シングル / レベル50固定 / 個体値31 / 努力値は「能力ポイント」表記
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
# M-C から取得元が champs.pokedb.tokyo に変わり、名前が全部日本語で来るようになった。
# ファイル名も ASCII に統一してある（zip に日本語名を入れると環境によっては化けて
# 取り出せないため、配布物とリポジトリで名前を分ける必要がなくなった）。
JSON_PATH = os.path.join(DATA, 'usage.json')
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

# 技名の誤りを読み込み時に直すための表。xlsx を直せなかった時代の名残で、いまは空。
# スピリットブレイク→ソウルクラッシュ / うでずもう→アームハンマー の2件が入っていたが、
# 一次データ（data/moves.csv と data/move_names_en_ja.json）を直したので不要になった。
# **新しく誤りを見つけたらここではなく CSV を直すこと。** 名前は moves.csv と
# move_names_en_ja.json の2箇所にあるので、両方直さないとビルドが止まる。
MOVE_NAME_FIX = {}


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


# 倒れた味方の数で威力が変わる技（おはかまいり）の前提。
# シングルは3体選出なので、味方が倒れる数は最大2。この手の技を撃つ／撃たれるのは
# 終盤で、そのときには2体落ちていることがほとんどなので、最大値で固定する。
# 戦況によって変わる値を技データには書けないため、ここで前提を1箇所に置く。
FAINTED_ALLIES = 2

_PER_FAINT_RE = re.compile(r'[（(](\d+)[＋+](\d+)[×xX*]人数[）)]')


def power_per_faint(effect, power):
    """「威力上昇（50＋50×人数）」から実際に使う威力を出す。書式が無ければ元の威力。
    一撃必殺・連続技と同じく、技名を並べずに効果欄から拾う。
    倒れた数だけは戦況なので、FAINTED_ALLIES の仮定で固定している。"""
    if not effect:
        return power
    m = _PER_FAINT_RE.search(effect)
    if not m:
        return power
    return float(m.group(1)) + float(m.group(2)) * FAINTED_ALLIES


def multi_damage(mh, power, attack, defense, stab=1.0, type_eff=1.0, extra=1.0,
                 skill_link=False, crit=False):
    """連続技の合計ダメージ。(最低回数×最低乱数, 最高回数×最高乱数) を返す。
    1発ずつ damage() を通して足すこと。各発で切り捨てが入るので、
    威力を合算してから1回で計算すると数値が合わない。"""
    def total(hits, idx):
        return sum(damage(power + mh['step'] * i, attack, defense,
                          stab, type_eff, extra, crit)[idx]
                   for i in range(hits))
    lo_hits = mh['max'] if skill_link else mh['min']
    return total(lo_hits, 0), total(mh['max'], 1)


# タイプ相性の例外。効果欄の「○○タイプに対して効果抜群になる」から拾う。
# フリーズドライ（こおりだがみずに抜群）が該当。技名を並べずに済むので、
# 同じ書き方の技が増えても勝手に効く。
TYPE_NAMES = {d for _, d in EFF}
_SUPER_RE = re.compile(r'(.+?)タイプに対して効果抜群')


def parse_type_override(effect):
    """{防御タイプ: 倍率} を返す。該当しなければ空。"""
    if not effect:
        return {}
    m = _SUPER_RE.search(effect)
    if not m:
        return {}
    text = m.group(1)
    for name in TYPE_NAMES:
        if text.endswith(name):
            return {name: 2.0}
    return {}


# 技データ: MOVES[技名] = {type, cat, power, acc, pri, effect, ranks, ohko}
MOVES = {}
for _r in _read_csv(MOVES_CSV):
    if not _r['name']:
        continue
    _effect = _r['effect'] or None
    _base_power = float(_r['power']) if _r['power'] else 0
    MOVES[fix_move_name(_r['name'])] = dict(
        type=_r['type'], cat=_r['category'],
        # CSVには技本来の威力を書き、倒れた味方の数による上昇はここで乗せる。
        # 「50」と書いてあるのに150で計算されるので、効果欄を読んで確認すること。
        power=power_per_faint(_effect, _base_power),
        acc=float(_r['accuracy']) if _r['accuracy'] else None,
        pri=float(_r['priority']) if _r['priority'] else 0.0,
        effect=_effect,
        ranks=parse_rank_change(_r.get('rank_change')),
        # 一撃必殺・連続技は技名を並べるのではなく効果欄から拾う。
        # 新しい技が増えても、効果欄に同じ書き方をしてあれば勝手に効く。
        ohko=bool(_effect and '一撃必殺' in _effect),
        # 「必ず急所に当たる」だけ拾う。「急所に当たりやすい」は確率なので数えない
        crit=bool(_effect and '必ず急所' in _effect),
        multi=parse_multi_hit(_effect, float(_r['power']) if _r['power'] else 0),
        type_override=parse_type_override(_effect))


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
        # メガリザードンX / Y、メガガブリアスZ のように末尾に記号が付く形態。
        # **Z を忘れないこと。** M-C で ガブリアス・ルカリオ・アブソル に
        # 通常メガとZメガの2種類ができた。Z を剥がさないと is_mega() が false になり、
        # メガ形態が普通のポケモン扱いで種族値もタイプも間違ったまま表に出る。
        if _rest[-1:] in ('X', 'Y', 'Z'):
            _rest = _rest[:-1]
        if any(_plain_key(_o) == _rest for _o in _names if _o != _n):
            MEGA_NAMES.add(_n)


def is_mega(name):
    """メガ形態かどうか。name.startswith('メガ') を直接使わないこと。"""
    return name in MEGA_NAMES


# メガ形態名 -> その通常形態名。MEGA_NAMES と同じ照合で作るので、
# ロトムのフォルム違いのような「同じ図鑑番号だがメガではない」ものは入らない。
# 選出補助でメガ／非メガを切り替えるのに使う。
# **sorted で回すこと。** MEGA_NAMES は集合なので、そのまま回すと実行のたびに
# 順序が変わる（Python の文字列ハッシュはプロセスごとにランダム）。この dict の
# 挿入順が dex.json の forms（リザードンの X / Y の並び）になるので、
# ソートしないと書き出すたびに差分が出て、CI の「コミット済みと一致するか」が落ちる。
MEGA_BASE = {}
for _n in sorted(MEGA_NAMES):
    _rest = _n[2:]
    if _rest[-1:] in ('X', 'Y', 'Z'):
        _rest = _rest[:-1]
    for _names in BY_DEX_NO.values():
        if _n not in _names:
            continue
        for _o in _names:
            if _o != _n and _plain_key(_o) == _rest:
                MEGA_BASE[_n] = _o
                break


# リージョンフォームにメガを紐付ける例外。
# フラエッテは図鑑に「フラエッテ(えいえん)」しか無く、メガフラエッテはその形態のメガ。
# 一方ライチュウ(アローラ)やヤドラン(ガラル)は通常形態が別に居て、メガはそちらのものなので、
# 「リージョンフォームにメガを付ける」を一般ルールにすると誤ってメガを生やしてしまう。
# 実際に該当するのはこの1件だけなので、一般化せず例外として書く。
REGION_FORM_MEGA = {'フラエッテ(えいえん)': 'メガフラエッテ'}


def resolve_form(entry, want_mega=False):
    """JSONの1エントリから、図鑑上の正しいポケモン名を返す。

    champs.pokedb.tokyo（M-C以降）は 'dex_name' に図鑑名がそのまま入っていて、
    リージョンフォームも名前に含まれている（'ダイケンキ(ヒスイ)'）。
    `pokemon_id` は全件 null、`region_form` / `mega_form` も全件空なので、
    **図鑑番号からの逆引きは使えない。** dex_name があればそれを正とする。
    図鑑に無い名前は PokemonNotFoundError（黙って別形態にしない）。

    以下は旧ソース（pkmnchamps・英語スラッグ）用の経路。取得元が止まったので
    もう動かないが、過去のデータで再現を取るために残してある。
    region_form を無視すると別形態の種族値で計算してしまうので必ずこれを通すこと。
    pokemon_id が図鑑に無ければ PokemonNotFoundError、region_form が指定されているのに
    対応する図鑑エントリが無ければ RegionFormError を投げる。どちらも黙って別形態の
    種族値で計算しないための安全弁（過去にヒスイダイケンキを通常種で計算したバグがある）。"""
    if entry.get('dex_name'):
        base = entry['dex_name']
        if base not in DEX:
            raise PokemonNotFoundError(base)
        # メガは「メガ」+名前。X / Y / Z がある種は複数返る（並びは図鑑の順）
        megas = [n for n in ('メガ' + base, 'メガ' + base + 'X',
                             'メガ' + base + 'Y', 'メガ' + base + 'Z') if n in DEX]
        if not megas and base in REGION_FORM_MEGA:
            megas = [REGION_FORM_MEGA[base]]
        if want_mega and megas:
            return megas[0], megas
        return base, megas

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


def move_eff(move, move_type, t1, t2=None):
    """技ごとの相性倍率。フリーズドライのように相性表と違う倍率になる技があるので、
    ダメージ計算は eff() ではなくこちらを通すこと。
    上書きは防御タイプ単位で掛かるので、複合タイプでは片方だけ差し替わる
    （フリーズドライはみず/じめんに 2×2＝4倍、みず/こおりに 2×0.5＝等倍）。"""
    override = (MOVES.get(move) or {}).get('type_override') or {}
    e = override.get(t1, EFF[(move_type, t1)])
    if t2:
        e *= override.get(t2, EFF[(move_type, t2)])
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
# 受けるダメージが増える防御特性。もふもふは接触技0.5倍だが、ほのお技だけ2倍になる。
DOUBLE_JA = {'もふもふ': ('ほのお',)}
DOUBLE_EN = {'fluffy': ('ほのお',)}
# 接触技を半減する防御特性
CONTACT_HALF = ('もふもふ', 'fluffy', 'はどうのぼうご', 'punching-glove')
# 受ける物理技を半減する特性（防御を2倍にして計算するのと同じ）。
# 物理か特殊かは技側の情報なので、呼び出し側から is_physical で渡す。
PHYSICAL_HALF = ('ファーコート', 'fur-coat')
# ability_mod が返す特性名を表示用の日本語に揃える
ABILITY_DISPLAY = {
    'levitate': 'ふゆう', 'flash-fire': 'もらいび', 'water-absorb': 'ちょすい',
    'storm-drain': 'よびみず', 'dry-skin': 'かんそうはだ', 'volt-absorb': 'ちくでん',
    'lightning-rod': 'ひらいしん', 'motor-drive': 'でんきエンジン', 'sap-sipper': 'そうしょく',
    'earth-eater': '土食い', 'thick-fat': 'あついしぼう', 'heatproof': 'たいねつ',
    'water-bubble': 'すいほう',
}
SOUND = {'ハイパーボイス', 'うたかたのアリア', 'ばくおんぱ', 'いびき', 'エコーボイス', 'りんしょう'}


# ---------------------------------------------------------------- フィールド
#
# **フィールドは「場の状態」で、張った側だけでなく両者に効く。**
# メガソーラー（自分の行動だけ晴れ扱い）の真似をして攻撃側だけに書くと、
# 相手が張ったサイコフィールドでこちらのエスパー技が1.3倍にならず、
# こちらの先制技も止まらない、という抜けになる。必ず対面の属性として扱うこと。
#
# 反映するのは**自分でフィールドを張るポケモンが対面に居るとき**だけ。
# 味方のイエッサンに依存するワイドフォース（61位グレンアルマ・122位メガフーディン）は、
# 1対1の表からは分からないので入れない（ダメージ表の手動切り替えで見る）。

TERRAIN_MAKERS = {'グラスメイカー': 'グラス', 'エレキメイカー': 'エレキ',
                  'サイコメイカー': 'サイコ', 'ミストメイカー': 'ミスト',
                  # 旧データ（英語スラッグ）用
                  'grassy-surge': 'グラス', 'electric-surge': 'エレキ',
                  'psychic-surge': 'サイコ', 'misty-surge': 'ミスト'}
# フィールドが1.3倍にするタイプ（第8世代以降。第7世代の1.5倍ではない）
TERRAIN_TYPE = {'グラス': 'くさ', 'エレキ': 'でんき',
                'サイコ': 'エスパー', 'ミスト': 'フェアリー'}
TERRAIN_BOOST = 1.3
# グラスフィールドが半減する技。**技名で持つ。** 「じめん技すべて」ではない
GRASS_HALVED = ('じしん', 'じならし', 'マグニチュード')
# フィールドで挙動が変わる技。効果欄の文面が技ごとにばらばらで機械的に導けないので、
# 一撃必殺・連続技とは違ってここだけは表で持つ（ウェザーボールと同じ扱い）。
#   power   … フィールド中の威力
#   mult    … 威力ではなく倍率で効くもの
#   pri     … 優先度の加算
#   ground  … 'self'=撃つ側 / 'target'=受ける側 のどちらが接地していれば効くか
#   any     … どのフィールドでも効く（だいちのはどうはタイプも変わる）
TERRAIN_MOVES = {
    'グラススライダー': dict(terrain='グラス', pri=1, ground='self'),
    'ワイドフォース': dict(terrain='サイコ', power=120.0, ground='self'),
    # ライジングボルトが2倍になるのは**相手が接地しているとき**。浮いている相手には乗らない
    'ライジングボルト': dict(terrain='エレキ', power=140.0, ground='target'),
    'ミストバースト': dict(terrain='ミスト', mult=1.5, ground='self'),
    'だいちのはどう': dict(any=True, power=100.0, retype=True, ground='self'),
}


def terrain_of(*mons):
    """この対面で張られているフィールド。両者の特性から決まる。無ければ None。

    どちらも張る場合は後から出た方が上書きするので本当は決まらない。
    いまの環境では自軍側に張る駒が居ないため起こらないが、起きたときは
    相手側を優先する（表は「相手が何をしてくるか」を見るものなので）。"""
    found = [TERRAIN_MAKERS[k] for mon in mons if mon
             for k in TERRAIN_MAKERS if k in (mon.get('ability') or '')]
    return found[0] if found else None


def is_grounded(types, ability='', item=''):
    """接地しているか。**フィールドは地上のポケモンにしか効かない。**
    ひこうタイプ・ふゆう・ふうせん は浮いているので、1.3倍も先制技封じも受けない。
    ライジングボルトの威力2倍が乗るかどうかもここで決まる。"""
    if 'ひこう' in (types or ()):
        return False
    ab = ability or ''
    if 'ふゆう' in ab or 'levitate' in ab:
        return False
    return 'ふうせん' not in (item or '')


def terrain_blocks_priority(terrain, defender_types, defender_ability, defender_item=''):
    """サイコフィールドは、接地している相手に先制技を通さない。
    打点そのものではなく「先に動けるか」に効くので、process_check 側でも見ること。"""
    return terrain == 'サイコ' and is_grounded(defender_types, defender_ability, defender_item)


def ability_mod(ability, move_type, mold_breaker=False, hp_full=True, is_sound=False,
                is_contact=False, is_physical=False):
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
    # もふもふ: ほのおは2倍、それ以外の接触技は0.5倍。両方に当てはまる技は無い
    for table in (DOUBLE_JA, DOUBLE_EN):
        for name, types in table.items():
            if name in ab and move_type in types:
                return 2.0, 'もふもふ'
    if any(k in ab for k in CONTACT_HALF) and is_contact:
        return 0.5, 'はどうのぼうご' if 'はどうのぼうご' in ab else 'もふもふ'
    if any(k in ab for k in PHYSICAL_HALF) and is_physical:
        return 0.5, 'ファーコート'
    if ('マルチスケイル' in ab or 'multiscale' in ab) and hp_full:
        return 0.5, 'マルチスケイル'
    if ('ぼうおん' in ab or 'soundproof' in ab) and is_sound:
        return 0.0, 'ぼうおん'
    if any(k in ab for k in ('ハードロック', 'フィルター', 'solid-rock', 'filter', 'prism-armor')):
        return 0.75, 'ハードロック'   # ※効果抜群のときのみ有効。呼び出し側で判定すること
    if 'ばけのかわ' in ab or 'disguise' in ab:
        return 1.0, 'ばけのかわ'
    # がんじょう: HP満タンなら必ず1残る。きあいのタスキと同じ扱いで、倍率ではなく手数+1
    if ('がんじょう' in ab or 'sturdy' in ab) and hp_full:
        return 1.0, 'がんじょう'
    return 1.0, ''


# ---------------------------------------------------------------- ダメージ計算

def damage(power, attack, defense, stab=1.0, type_eff=1.0, extra=1.0, crit=False):
    """レベル50固定のダメージ計算。(最低乱数, 最高乱数) を返す。
    stab   : タイプ一致補正（通常1.5 / てきおうりょく2.0）
    type_eff: タイプ相性 × 防御特性の倍率
    extra  : その他の乗算補正（いのちのたま1.3 / きれあじ1.5 / フェアリースキン1.2 など）
    crit   : 必ず急所に当たる技（トリックフラワーなど）。1.5倍
    丸めは 基礎 → 急所 → 乱数 → 一致 → 相性 → その他 の順に切り捨てる。

    **急所は乱数より前。** 本家の式が
    「基礎ダメージ × 急所 × 乱数 × 一致 × 相性 × その他」の順で、
    急所倍率は基礎ダメージ（+2 まで含めた値）に掛かる。
    威力を1.5倍する形で代用すると +2 の扱いがずれて1前後合わなくなるので、
    ここで段を分けている。
    """
    base = int(int(2 * 50 / 5 + 2) * power * attack / defense / 50) + 2
    if crit:
        base = int(base * 1.5)

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
