"""
自分のパーティ定義。

`party.txt`（リポジトリ直下）を読み込んで PARTY を組み立てる。構成を変えるときは
`party.txt` をゲーム内のステータス画面を見ながら編集すればよく、このファイルは触らない。

重要: `party.txt` に書く実数値は「ゲーム内のステータス画面に表示される値」= メガシンカ前の値。
      能力ポイントはこの表示値・種族値・性格から逆算する（1ポイントで実数値がちょうど1
      上がるので解は一意）。メガ形態は同じ能力ポイントをメガ側の種族値に当てはめて
      generate.py 側で計算し直す。ポイント自体を再計算してはいけない
      （過去にメガギャラドスをA177のまま計算し続けて全ての数値が狂った）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import ROOT, DEX, MOVES, NATURE, NAT_JA

PARTY_TXT = os.path.join(ROOT, 'party.txt')

NAT_JA_TO_EN = {v: k for k, v in NAT_JA.items()}
STAT_KEYS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']
STAT_LABELS = ['H', 'A', 'B', 'C', 'D', 'S']

MOLD_BREAKER_ABILITIES = {'かたやぶり'}
FAIRY_SKIN_ABILITIES = {'フェアリースキン'}
SHARPNESS_ABILITIES = {'きれあじ'}
BOOSTING_MOVES = {'りゅうのまい', 'つるぎのまい', 'ちょうのまい', 'めいそう'}

MAX_POINTS_PER_STAT = 32
MAX_POINTS_TOTAL = 66

# 撃つと次のターンに交代できない技。判定が同じなら他の技を優先表示する。
DRAWBACK_MOVES = {'はかいこうせん', 'ギガインパクト'}

# きれあじ（威力1.5倍）が乗る斬撃技
SLASH_MOVES = {'サイコカッター', 'せいなるつるぎ', 'リーフブレード', 'つじぎり',
               'シャドークロー', 'アクアカッター', 'きりさく', 'ネズミざん',
               'ひけん・ちえなみ', 'シェルブレード'}

# かたいツメ（接触技1.3倍）の判定に使う。物理でも じしん・いわなだれ のように接触しない技が
# あり、規則で決め打ちすると外れるので、推測せず技ごとに明示する。
# かたいツメ持ちの相手がここに無い技を使っているとビルドが警告する（黙って1.0倍にしないため）。
CONTACT_MOVES = {'アームハンマー', 'ボディプレス', 'サイコファング',
                 'バレットパンチ', 'かみなりパンチ', 'れいとうパンチ', 'ほのおのパンチ',
                 'ドレインパンチ', 'コメットパンチ', 'インファイト', 'とんぼがえり',
                 'はたきおとす', 'ふいうち', 'じゃれつく', 'かわらわり', 'しんそく',
                 'アイアンヘッド', 'たきのぼり', 'アクアブレイク', 'クイックターン',
                 'しねんのずつき', 'アイススピナー', 'アクアジェット', 'サイコカッター',
                 'ほのおのキバ', 'イカサマ', 'トリックフラワー', 'トリプルアクセル',
                 'ウェーブタックル', 'もろはのずつき', 'しのびよる', 'せいなるつるぎ',
                 'アクアカッター', 'シェルブレード', 'ダブルウイング'}
NON_CONTACT_MOVES = {'じしん', 'いわなだれ', 'がんせきふうじ', 'ロックブラスト',
                     'ラスターカノン', 'はどうだん', 'しんくうは', 'みずしゅりけん',
                     'なみのり', 'ハイドロポンプ', 'れいとうビーム', 'あくのはどう',
                     'ヘドロウェーブ', 'マッドショット', 'パワージェム', 'つのドリル',
                     'タネマシンガン', 'ミサイルばり', 'つららばり'}

# 一撃必殺技
OHKO_MOVES = {'つのドリル', 'じわれ', 'ハサミギロチン', 'ぜったいれいど'}

# 変化技（ダメージ計算の対象外）
STATUS_MOVES = {'ステルスロック', 'まきびし', 'あくび', 'ふきとばし', 'はねやすめ',
                'りゅうのまい', 'つるぎのまい', 'ちょうのまい', 'めいそう', 'どくどく'}

# 表に載せる相手の順位の上限
THREAT_RANK_LIMIT = 45

# 努力値配分パターンを2行に分ける閾値（生の採用率%）
SPREAD_THRESHOLD = 10.0

# 被弾の主表示に使う技の採用率の下限(%)。
# これ以下しか採用されていない技がたまたま最大打点になっても、それを主表示にすると
# 「ほぼ来ない技」で身構えることになる。主要技での最大打点を主に出し、
# 低採用の技が上回る場合だけ補足として併記する。
RARE_MOVE_THRESHOLD = 10.0


class PartyError(Exception):
    """party.txt の入力ミス。ビルドを止めて内容を表示するために使う。"""


def _stat_value(base, points, is_hp, nat_mult):
    """能力ポイントから実数値を1ステータス分だけ計算する（engine.stats と同じ式）。"""
    ev = points * 8
    if is_hp:
        return int((2 * base + 31 + ev // 4) * 50 // 100) + 60
    v = int((2 * base + 31 + ev // 4) * 50 // 100) + 5
    if nat_mult != 1.0:
        v = int(v * nat_mult)
    return v


def _nat_mult(nature_en, stat_key):
    if nature_en not in NATURE:
        return 1.0
    up, dn = NATURE[nature_en]
    if stat_key == up:
        return 1.1
    if stat_key == dn:
        return 0.9
    return 1.0


def _find_points(base, target, is_hp, nat_mult, label, who):
    """実数値から能力ポイントを逆算する。0〜32を超えて総当たりし、
    どのポイントでも一致しない／32ポイントを超える、を区別してエラーにする。"""
    search_max = MAX_POINTS_PER_STAT + 20
    matches = [p for p in range(search_max + 1)
               if _stat_value(base, p, is_hp, nat_mult) == target]
    if not matches:
        achievable = sorted({_stat_value(base, p, is_hp, nat_mult)
                             for p in range(MAX_POINTS_PER_STAT + 1)})
        raise PartyError(
            f'{who}: {label}の実数値{target}になる能力ポイントがありません。\n'
            f'      0〜{MAX_POINTS_PER_STAT}ポイントで取りうる値: {achievable}')
    p = min(matches)
    if p > MAX_POINTS_PER_STAT:
        raise PartyError(
            f'{who}: {label}の実数値{target}にはポイント{p}が必要ですが、'
            f'1ステータスの上限{MAX_POINTS_PER_STAT}を超えています。')
    return p


def _ev_points(base, targets, nature_en, who):
    points = []
    for i, key in enumerate(STAT_KEYS):
        is_hp = (i == 0)
        mult = 1.0 if is_hp else _nat_mult(nature_en, key)
        points.append(_find_points(base[i], targets[i], is_hp, mult, STAT_LABELS[i], who))
    total = sum(points)
    if total > MAX_POINTS_TOTAL:
        breakdown = ' '.join(f'{l}{p}' for l, p in zip(STAT_LABELS, points))
        raise PartyError(
            f'{who}: 能力ポイントの合計が{total}で、上限{MAX_POINTS_TOTAL}を超えています。'
            f'（内訳 {breakdown}）')
    return points


def _parse_blocks(text):
    """空行区切りで1体4行のブロックに分ける。# で始まる行はコメントとして無視する。"""
    blocks, cur = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('#'):
            continue
        if not line:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append(cur)
    return blocks


def _ability_flags(ability):
    return dict(
        mold_breaker=ability in MOLD_BREAKER_ABILITIES,
        fairy_skin=ability in FAIRY_SKIN_ABILITIES,
        sharpness=ability in SHARPNESS_ABILITIES,
    )


def _make_member(mid, name, form, species, ev, nature_en, ability, item, moves, scarf):
    flags = _ability_flags(ability)
    boosting = next((mv for mv in moves if mv in BOOSTING_MOVES), None)
    return dict(
        id=mid, name=name, form=form,
        species=species, ev=list(ev), nature=nature_en,
        ability=ability, item=item, moves=moves, scarf=scarf,
        mold_breaker=flags['mold_breaker'], fairy_skin=flags['fairy_skin'],
        sharpness=flags['sharpness'], life_orb=(item == 'いのちのたま'),
        boosting_move=boosting,
    )


def _parse_party(text):
    blocks = _parse_blocks(text)
    if not blocks:
        raise PartyError('party.txt にパーティが1体も見つかりません。')

    members = []
    for bi, lines in enumerate(blocks, 1):
        who = f'party.txt {bi}体目'
        if len(lines) != 4:
            raise PartyError(f'{who}: 1体は4行のはずが{len(lines)}行あります: {lines}')
        line1, line2, line3, line4 = lines

        if ' @ ' not in line1:
            raise PartyError(f'{who}: 1行目は「ポケモン名 @ 持ち物」の形式にしてください: {line1!r}')
        name, item = (s.strip() for s in line1.split(' @ ', 1))
        who = f'{name}（{who}）'
        if name not in DEX:
            raise PartyError(f'{who}: ポケモン名「{name}」が図鑑に見つかりません。')

        if ' / ' not in line2:
            raise PartyError(f'{who}: 2行目は「性格 / 特性」の形式にしてください: {line2!r}')
        nature_ja, ability = (s.strip() for s in line2.split(' / ', 1))
        nature_en = NAT_JA_TO_EN.get(nature_ja)
        if nature_en is None:
            raise PartyError(f'{who}: 性格「{nature_ja}」が分かりません。')
        base_ab = DEX[name]['ab'] or ''
        if ability not in base_ab:
            raise PartyError(
                f'{who}: 特性「{ability}」が{name}の特性データに見つかりません'
                f'（データ上の特性: {base_ab}）。')

        parts = line3.split('-')
        if len(parts) != 6 or not all(p.strip().isdigit() for p in parts):
            raise PartyError(f'{who}: 3行目は実数値 H-A-B-C-D-S の形式にしてください: {line3!r}')
        targets = [int(p) for p in parts]

        moves = [m.strip() for m in line4.split(' / ') if m.strip()]
        if not moves or len(moves) > 4:
            raise PartyError(f'{who}: 技は1〜4個にしてください: {line4!r}')
        for mv in moves:
            if mv not in MOVES:
                raise PartyError(f'{who}: 技「{mv}」が技データに見つかりません。')

        ev = _ev_points(DEX[name]['base'], targets, nature_en, who)

        mega_name = 'メガ' + name
        has_mega = mega_name in DEX and 'ナイト' in item

        if has_mega:
            mega_ability = DEX[mega_name]['ab']
            members.append(_make_member(
                f'p{bi:02d}_mega', name, 'メガ', mega_name, ev, nature_en,
                mega_ability, item, moves, scarf=False))
            members.append(_make_member(
                f'p{bi:02d}_base', name, '非メガ', name, ev, nature_en,
                ability, '—', moves, scarf=False))
        else:
            form = 'スカーフ' if item == 'こだわりスカーフ' else ''
            members.append(_make_member(
                f'p{bi:02d}', name, form, name, ev, nature_en,
                ability, item, moves, scarf=(item == 'こだわりスカーフ')))

    return members


try:
    with open(PARTY_TXT, encoding='utf-8') as _f:
        PARTY = _parse_party(_f.read())
except PartyError as _e:
    print(f'party.txt の読み込みに失敗しました:\n  {_e}')
    sys.exit(1)
