#!/usr/bin/env python3
"""
ブラウザ側（index.html / party.html）が読む JSON を appdata/ に書き出す。

    python build/export_app_data.py

相手の型を作る処理（配分の集約・メガ形態の判定・リージョンフォーム・マルチスケイルや
へんげんじざいの行分割）は Python 側に残し、ここでは計算済みの結果だけを渡す。
JS に移植するのはパーティの解析とダメージ計算だけにして、移植の危険を小さくしている。

技データ・図鑑・タイプ相性・技の分類は、JS 側で二重に定義せずここから配る。
定義が2箇所に散ると必ず片方だけ直して食い違うため。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import (ROOT, DEX, MOVES, EFF, NATURE, NAT_JA, IDX,
                    IMMUNE_JA, IMMUNE_EN, HALF_JA, HALF_EN, DOUBLE_JA, DOUBLE_EN,
                    CONTACT_HALF, PHYSICAL_HALF, ABILITY_DISPLAY, SOUND, MEGA_BASE, is_mega,
                    TERRAIN_MAKERS, TERRAIN_TYPE, TERRAIN_BOOST, TERRAIN_MOVES, GRASS_HALVED,
                    WEATHER_MAKERS, WEATHER_TYPE_MULT, WEATHER_DEF_BOOST, WEATHER_MOVES,
                    SAND_SAFE_TYPES, SAND_SAFE_ABILITIES, SUN_HEAL_MOVES,
                    VERDICT_RANK, VERDICT_PLUS_ONE, STRIPPABLE_ABILITIES,
                    MEGA_NAMES, ABILITIES, self_boost)
from party import (DRAWBACK_MOVES, SLASH_MOVES, OHKO_MOVES, STATUS_MOVES,
                   CONTACT_MOVES, NON_CONTACT_MOVES, BOOSTING_MOVES, PUNCH_MOVES, PULSE_MOVES,
                   MOLD_BREAKER_ABILITIES, FAIRY_SKIN_ABILITIES, SHARPNESS_ABILITIES,
                   MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL, RARE_MOVE_THRESHOLD,
                   THREAT_RANK_LIMIT)
import generate
import partycode
from generate import (build_threats, TYPE_COLOR, VERDICT_CLASS, ABILITY_JA,
                      ITEM_JA, MULTI_HIT, ABILITY_HANDLING, SKIN_ABILITIES,
                      ITEM_DAMAGE, RECOVERY_MOVES, MAX_TURNS, SUPER_TAKE_PH,
                      type_weakness,
                      type_effects, ability_type_effects)

OUT_DIR = os.path.join(ROOT, 'appdata')


def threat_rows():
    """表に出す相手の行。実数値まで計算済みで渡す。"""
    out = []
    for t in build_threats():
        out.append(dict(
            rank=t['rank'], name=t['name'], pattern=t['pattern'], share=t['share'],
            multi=t['multi'], form=t['form'], hp_full=t['hp_full'], protean=t['protean'],
            nature=t['nature'], types=[t['types'][0], t['types'][1]], st=t['st'],
            # 特性は生の値（英語名か図鑑の連結文字列）と表示用の日本語の両方を渡す。
            # ability_mod は英語名でも日本語でも引けるようになっているので生の値も要る。
            ability=t['ability'], ability_ja=ABILITY_JA.get(t['ability'], t['ability']),
            speed=t['speed'], scarf=t['scarf'], item=t['item'],
            moves=[{'name': mv, 'usage': u} for mv, u in t['moves_use']],
            # 弱点は Python 側で出して渡す。JS で相性表を引き直すと、
            # タイプ別に効く特性（ふゆう・あついしぼう等）の扱いが必ず食い違う
            **dict(zip(('weak4', 'weak2'), type_weakness(t['types'], t['ability']))),
        ))
    return out


def dex_rows():
    """パーティ編集と選出補助の相性表で使う図鑑。
    種族値・タイプ・特性・メガ形態かどうか・18タイプぶんの素の相性倍率。

    eff は**特性を含まない素の値**。特性による変化は rules.abilityTypeEffect を
    掛けて JS 側で出す（どの特性を効かせるかの判断は Python 側に残してある）。
    ab_list が特性の正しい一覧で、ab は既存の部分一致のために残している連結文字列。"""
    # forms は「メガ／非メガの切り替え先」。同じ図鑑番号でも、ロトムのフォルム違いのような
    # メガではないものは入らない（切り替えの相手ではない）。通常形態を先頭にした並び。
    forms = {}
    for mega, base in MEGA_BASE.items():
        forms.setdefault(base, [base])
        if mega not in forms[base]:
            forms[base].append(mega)
    chain = {}
    for base, names in forms.items():
        for n in names:
            chain[n] = names
    return {name: dict(t1=d['t1'], t2=d['t2'], ab=d['ab'], ab_list=d['ab_list'],
                       base=d['base'], mega=name in MEGA_NAMES,
                       forms=chain.get(name, []),
                       eff=type_effects((d['t1'], d['t2'])))
            for name, d in DEX.items()}


def move_rows():
    # multi / ohko は効果欄から導いた結果。JS側で同じ解析を書くと必ず食い違うので、
    # 解析済みのものを渡してJSは使うだけにする。
    return {name: dict(type=m['type'], cat=m['cat'], power=m['power'],
                       acc=m['acc'], pri=m['pri'], effect=m['effect'],
                       multi=m['multi'], ohko=m['ohko'], crit=m['crit'],
                       type_override=m['type_override'])
            for name, m in MOVES.items()}


def type_chart():
    """EFF[(攻撃, 防御)] を {攻撃: {防御: 倍率}} に組み替える。"""
    out = {}
    for (atk, dfn), v in EFF.items():
        out.setdefault(atk, {})[dfn] = v
    return out


def rules():
    """計算と入力チェックに使う定数。JS側で書き写さずここから読む。"""
    return dict(
        nature={k: list(v) for k, v in NATURE.items()},
        natureJa=NAT_JA,
        statIndex=IDX,
        # ability_mod は「先頭から順に照合して最初に一致したものを返す」ので、
        # 辞書のままJSONに出すと sort_keys で順序が変わって挙動がずれる。
        # Python 側の定義順を保つために配列で渡す。
        immuneJa=[[k, v] for k, v in IMMUNE_JA.items()],
        immuneEn=[[k, v] for k, v in IMMUNE_EN.items()],
        halfJa=[[k, list(v)] for k, v in HALF_JA.items()],
        halfEn=[[k, list(v)] for k, v in HALF_EN.items()],
        # もふもふ。受けるダメージが増える側と、接触技を半減する側の2枚。
        doubleJa=[[k, list(v)] for k, v in DOUBLE_JA.items()],
        doubleEn=[[k, list(v)] for k, v in DOUBLE_EN.items()],
        contactHalf=list(CONTACT_HALF),
        physicalHalf=list(PHYSICAL_HALF),
        # フィールド。どの特性がどれを張るか・どの技がどう変わるかの判断は Python 側。
        # JS は受け取って掛けるだけ（abilityTypeEffect と同じ分担）
        terrainMakers=TERRAIN_MAKERS,
        terrainType=TERRAIN_TYPE,
        terrainBoost=TERRAIN_BOOST,
        terrainMoves=TERRAIN_MOVES,
        grassHalved=list(GRASS_HALVED),
        # 天気。フィールドと同じ分担（判断は Python、JS は掛けるだけ）
        weatherMakers=WEATHER_MAKERS,
        weatherTypeMult=WEATHER_TYPE_MULT,
        weatherDefBoost={k: list(v) for k, v in WEATHER_DEF_BOOST.items()},
        weatherMoves=WEATHER_MOVES,
        sandSafeTypes=list(SAND_SAFE_TYPES),
        sandSafeAbilities=list(SAND_SAFE_ABILITIES),
        sunHealMoves=list(SUN_HEAL_MOVES),
        abilityDisplay=ABILITY_DISPLAY,
        abilityJa=ABILITY_JA,
        abilityHandling=ABILITY_HANDLING,
        abilities=ABILITIES,
        itemJa=ITEM_JA,
        sound=sorted(SOUND),
        slashMoves=sorted(SLASH_MOVES),
        contactMoves=sorted(CONTACT_MOVES),
        punchMoves=sorted(PUNCH_MOVES),
        pulseMoves=sorted(PULSE_MOVES),
        # 処理判定（generate.process_check）で使う。JS側で書き写さない
        recoveryMoves=sorted(RECOVERY_MOVES),
        maxTurns=MAX_TURNS,
        # 選出補助で★を付ける境目。判定ではなく表示の線引き
        superTakePh=SUPER_TAKE_PH,
        nonContactMoves=sorted(NON_CONTACT_MOVES),
        ohkoMoves=sorted(OHKO_MOVES),
        statusMoves=sorted(STATUS_MOVES),
        drawbackMoves=sorted(DRAWBACK_MOVES),
        boostingMoves=sorted(BOOSTING_MOVES),
        # 積み技ごとに「どの能力が何段階上がるか」。JS側で解析を書き直すと食い違うので、
        # 技データから導いた結果をそのまま渡す。
        boostStages={m: self_boost(m) for m in sorted(BOOSTING_MOVES)},
        moldBreakerAbilities=sorted(MOLD_BREAKER_ABILITIES),
        fairySkinAbilities=sorted(FAIRY_SKIN_ABILITIES),
        sharpnessAbilities=sorted(SHARPNESS_ABILITIES),
        multiHit=MULTI_HIT,
        typeColor=TYPE_COLOR,
        # 相性表の列の並び。dex.eff の並びと必ず同じにすること
        typeOrder=list(TYPE_COLOR),
        # タイプ別に効く防御特性だけの表。JS はこれを掛けるだけにする
        abilityTypeEffect=ability_type_effects(),
        verdictClass={k: v[0] for k, v in VERDICT_CLASS.items()},
        verdictColor={k: v[1] for k, v in VERDICT_CLASS.items()},
        verdictRank=VERDICT_RANK,
        verdictPlusOne=VERDICT_PLUS_ONE,
        strippableAbilities=list(STRIPPABLE_ABILITIES),
        skinAbilities=SKIN_ABILITIES,
        itemDamage=ITEM_DAMAGE,
        maxPointsPerStat=MAX_POINTS_PER_STAT,
        maxPointsTotal=MAX_POINTS_TOTAL,
        rareMoveThreshold=RARE_MOVE_THRESHOLD,
        threatRankLimit=THREAT_RANK_LIMIT,
    )


def golden():
    """JS移植が正しいか確かめるための期待値。
    現行のPython実装で party.txt の6体ぶんを計算した結果をそのまま置く。
    ブラウザ側で同じ入力から同じ数字が出ることを確認するために使う。"""
    from party import PARTY
    members = generate.build_members()
    threats = build_threats()
    rows = []
    for ti, t in enumerate(threats):
        for m in members:
            hits = [generate.my_hit(m, mv, t) for mv in m['moves']]
            primary, alt = generate.choose_move(hits)
            if not primary:
                continue
            back = generate.their_hit(t, m)
            sr = generate.sr_damage(t)
            hp_sr = max(t['st'][0] - sr, 1)
            hits_sr = [generate.my_hit(m, mv, t, hp_sr) for mv in m['moves']]
            primary_sr, _ = generate.choose_move(hits_sr)
            boosted = generate.boosted_hit(m, t)
            proc_ok, _, proc_info = generate.process_check(m, t)
            rows.append(dict(
                threat=ti, member=m['id'],
                move=primary['move'], lo=primary['lo'], hi=primary['hi'],
                verdict=primary['verdict'], pl=primary['pl'], ph=primary['ph'],
                srVerdict=primary_sr['verdict'] if primary_sr else None,
                srMove=primary_sr['move'] if primary_sr else None,
                backMove=back['move'], backPh=back['ph'],
                backRare=back['rare']['move'] if back.get('rare') else None,
                backStripped=back['stripped']['ph'] if back.get('stripped') else None,
                backDisguise=bool(back.get('disguise')),
                primaryDisguise=bool(primary.get('disguise')),
                primaryHits=primary.get('hits'),
                # 処理判定はJS側にも移植してあるので、期待値に入れて突き合わせる
                processed=proc_ok,
                # 超有利（選出補助の★）もJS側と突き合わせる
                processSuper=proc_info['super'],
                # フィールドは優先度を動かす（グラススライダー+1、サイコは先制技を消す）。
                # 打点の数字だけ見ていると優先度の移植漏れに気づけないので明示的に比べる
                primaryPri=primary.get('pri'), backPri=back.get('pri'),
                terrain=primary.get('terrain'), weather=primary.get('weather'),
                primaryAcc=primary.get('acc'),
                boostMove=boosted['move'] if boosted else None,
                boostPh=boosted['ph'] if boosted else None,
                boostStages=boosted['stages'] if boosted else None,
                srDamage=sr,
            ))
    with open(os.path.join(ROOT, 'party.txt'), encoding='utf-8') as f:
        party_text = f.read()
    # 文字列コードもJS移植の突き合わせ対象にする。Python が作ったコードを
    # ブラウザで復元し、さらに再符号化して同じ文字列になるかを見る
    return dict(partyText=party_text,
                partyCode=partycode.encode(PARTY),
                party=[dict(id=p['id'], name=p['name'], form=p['form'],
                            species=p['species'], ev=p['ev'], nature=p['nature'],
                            st=m['st'])
                       for p, m in zip(PARTY, members)],
                rows=rows)


def code_data():
    """パーティの文字列コード（assets/partycode.js）が読むもの。

    文字集合・台帳・場合の数の表は**すべて Python 側が一次情報**で、JS には結果だけ渡す。
    JS 側で作り直すと、同じパーティから違うコードが出る。
    台帳は追記専用なので、ここで data/code_dict.json も最新にする。"""
    reg, added = partycode.sync_registry()
    if added:
        for key, names in added.items():
            print(f'  台帳に追記: {key} {len(names)}件 '
                  f'({"、".join(names[:3])}{" ほか" if len(names) > 3 else ""})')
    for key, cap in partycode.CAPACITY.items():
        used = len(reg[key])
        if used > cap * 0.8:
            print(f'  警告: 台帳の {key} が {used}/{cap} 件。'
                  f'枠を超えると VERSION を上げる必要があります')
    return dict(version=partycode.VERSION, alphabet=partycode.ALPHABET,
                pokemon=reg['pokemon'], moves=reg['moves'],
                items=reg['items'], natures=reg['natures'],
                evCount=partycode.EV_COUNT,
                # 基数は**枠**であって登録件数ではない。JS 側で len() を使わないこと
                capPokemon=partycode.CAP_POKEMON, capMoves=partycode.CAP_MOVES,
                capItems=partycode.CAP_ITEMS, capNatures=partycode.CAP_NATURES,
                maxParty=partycode.MAX_PARTY, maxItemLen=partycode.MAX_ITEM_LEN,
                checkMod=partycode.CHECK_MOD,
                maxPointsTotal=MAX_POINTS_TOTAL, maxPointsPerStat=MAX_POINTS_PER_STAT)


def write(name, obj):
    path = os.path.join(OUT_DIR, name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
        f.write('\n')
    return path, os.path.getsize(path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0
    for name, obj in [('threats.json', threat_rows()),
                      ('dex.json', dex_rows()),
                      ('moves.json', move_rows()),
                      ('types.json', type_chart()),
                      ('rules.json', rules()),
                      ('code.json', code_data()),
                      ('golden.json', golden())]:
        path, size = write(name, obj)
        total += size
        print(f'  {os.path.basename(path):16} {size / 1024:7.1f} KB')
    print(f'書き出し完了: {OUT_DIR}  (合計 {total / 1024:.1f} KB)')


if __name__ == '__main__':
    main()
