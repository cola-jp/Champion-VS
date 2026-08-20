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
                    IMMUNE_JA, IMMUNE_EN, HALF_JA, HALF_EN, ABILITY_DISPLAY, SOUND,
                    VERDICT_RANK, MEGA_NAMES, ABILITIES)
from party import (DRAWBACK_MOVES, SLASH_MOVES, OHKO_MOVES, STATUS_MOVES,
                   CONTACT_MOVES, NON_CONTACT_MOVES, BOOSTING_MOVES,
                   MOLD_BREAKER_ABILITIES, FAIRY_SKIN_ABILITIES, SHARPNESS_ABILITIES,
                   MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL, RARE_MOVE_THRESHOLD,
                   THREAT_RANK_LIMIT)
import generate
from generate import (build_threats, TYPE_COLOR, VERDICT_CLASS, ABILITY_JA,
                      ITEM_JA, MULTI_HIT, ABILITY_HANDLING)

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
        ))
    return out


def dex_rows():
    """パーティ編集で使う図鑑。種族値・タイプ・特性・メガ形態かどうか。"""
    return {name: dict(t1=d['t1'], t2=d['t2'], ab=d['ab'], base=d['base'],
                       mega=name in MEGA_NAMES)
            for name, d in DEX.items()}


def move_rows():
    return {name: dict(type=m['type'], cat=m['cat'], power=m['power'],
                       acc=m['acc'], pri=m['pri'], effect=m['effect'])
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
        abilityDisplay=ABILITY_DISPLAY,
        abilityJa=ABILITY_JA,
        abilityHandling=ABILITY_HANDLING,
        abilities=ABILITIES,
        itemJa=ITEM_JA,
        sound=sorted(SOUND),
        slashMoves=sorted(SLASH_MOVES),
        contactMoves=sorted(CONTACT_MOVES),
        nonContactMoves=sorted(NON_CONTACT_MOVES),
        ohkoMoves=sorted(OHKO_MOVES),
        statusMoves=sorted(STATUS_MOVES),
        drawbackMoves=sorted(DRAWBACK_MOVES),
        boostingMoves=sorted(BOOSTING_MOVES),
        moldBreakerAbilities=sorted(MOLD_BREAKER_ABILITIES),
        fairySkinAbilities=sorted(FAIRY_SKIN_ABILITIES),
        sharpnessAbilities=sorted(SHARPNESS_ABILITIES),
        multiHit=MULTI_HIT,
        typeColor=TYPE_COLOR,
        verdictClass={k: v[0] for k, v in VERDICT_CLASS.items()},
        verdictColor={k: v[1] for k, v in VERDICT_CLASS.items()},
        verdictRank=VERDICT_RANK,
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
            rows.append(dict(
                threat=ti, member=m['id'],
                move=primary['move'], lo=primary['lo'], hi=primary['hi'],
                verdict=primary['verdict'], pl=primary['pl'], ph=primary['ph'],
                srVerdict=primary_sr['verdict'] if primary_sr else None,
                srMove=primary_sr['move'] if primary_sr else None,
                backMove=back['move'], backPh=back['ph'],
                backRare=back['rare']['move'] if back.get('rare') else None,
                boostMove=boosted['move'] if boosted else None,
                boostPh=boosted['ph'] if boosted else None,
                srDamage=sr,
            ))
    with open(os.path.join(ROOT, 'party.txt'), encoding='utf-8') as f:
        party_text = f.read()
    return dict(partyText=party_text,
                party=[dict(id=p['id'], name=p['name'], form=p['form'],
                            species=p['species'], ev=p['ev'], nature=p['nature'],
                            st=m['st'])
                       for p, m in zip(PARTY, members)],
                rows=rows)


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
                      ('golden.json', golden())]:
        path, size = write(name, obj)
        total += size
        print(f'  {os.path.basename(path):16} {size / 1024:7.1f} KB')
    print(f'書き出し完了: {OUT_DIR}  (合計 {total / 1024:.1f} KB)')


if __name__ == '__main__':
    main()
