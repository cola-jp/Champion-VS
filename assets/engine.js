/* ダメージ計算エンジン。build/engine.py と build/generate.py からの移植。
 *
 * 数値は Python 版と1ずつ一致させること。appdata/golden.json に Python で計算した
 * 期待値が入っていて、Engine.selfTest() で全件突き合わせできる。ここを変えたら必ず流す。
 *
 * 移植で踏みやすいところ:
 *   - Python の int() は 0 方向への切り捨て。ここでは Math.trunc を使う（Math.round ではない）。
 *   - Python の round() は「ちょうど .5 は偶数側」。JS の Math.round は切り上げなので
 *     そのまま使うと %表示が 1 ずれる。pyRound() を使うこと。
 *   - 丸めの順番（基礎 → 乱数 → 一致 → 相性 → その他）は変えない。1〜2ずれて判定が変わる。
 */
'use strict';

const Engine = (() => {
  let DEX = {}, MOVES = {}, TYPES = {}, R = {};
  let SLASH, OHKO, STATUS, DRAWBACK, BOOSTING, CONTACT, PUNCH, PULSE, SOUND_SET;

  function load(data) {
    DEX = data.dex;
    MOVES = data.moves;
    TYPES = data.types;
    R = data.rules;
    SLASH = new Set(R.slashMoves);
    OHKO = new Set(R.ohkoMoves);
    STATUS = new Set(R.statusMoves);
    DRAWBACK = new Set(R.drawbackMoves);
    BOOSTING = new Set(R.boostingMoves);
    CONTACT = new Set(R.contactMoves);
    PUNCH = new Set(R.punchMoves);
    PULSE = new Set(R.pulseMoves);
    SOUND_SET = new Set(R.sound);
  }

  /* Python の round(): ちょうど .5 のときだけ偶数側に寄せる。正の数しか来ない前提。 */
  function pyRound(x) {
    const f = Math.floor(x);
    const d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
  }

  // ------------------------------------------------------------ 実数値

  function stats(base, evPoints, nature) {
    const out = [];
    for (let i = 0; i < 6; i++) {
      const ev = evPoints[i] * 8;
      const core = Math.floor((2 * base[i] + 31 + Math.floor(ev / 4)) * 50 / 100);
      out.push(i === 0 ? core + 60 : core + 5);
    }
    const nat = R.nature[nature];
    if (nat) {
      const [up, dn] = nat;
      out[R.statIndex[up]] = Math.trunc(out[R.statIndex[up]] * 1.1);
      out[R.statIndex[dn]] = Math.trunc(out[R.statIndex[dn]] * 0.9);
    }
    return out;
  }

  /* 実数値1つ分。能力ポイントの逆算に使う（build/party.py の _stat_value と同じ式）。 */
  function statValue(base, points, isHp, natMult) {
    const ev = points * 8;
    const core = Math.floor((2 * base + 31 + Math.floor(ev / 4)) * 50 / 100);
    if (isHp) return core + 60;
    const v = core + 5;
    return natMult === 1 ? v : Math.trunc(v * natMult);
  }

  function natMult(nature, statKey) {
    const nat = R.nature[nature];
    if (!nat) return 1;
    if (statKey === nat[0]) return 1.1;
    if (statKey === nat[1]) return 0.9;
    return 1;
  }

  // ------------------------------------------------------------ 相性と特性

  function eff(moveType, t1, t2) {
    let e = TYPES[moveType][t1];
    if (t2) e *= TYPES[moveType][t2];
    return e;
  }

  /* 技ごとの相性倍率。フリーズドライのように相性表と違う倍率になる技があるので、
     ダメージ計算は eff() ではなくこちらを通すこと。
     上書きは防御タイプ単位で掛かるので、複合タイプでは片方だけ差し替わる
     （フリーズドライはみず/ひこうに 2×2＝4倍）。 */
  function moveEff(move, moveType, t1, t2) {
    const ov = (MOVES[move] && MOVES[move].type_override) || {};
    let e = ov[t1] !== undefined ? ov[t1] : TYPES[moveType][t1];
    if (t2) e *= ov[t2] !== undefined ? ov[t2] : TYPES[moveType][t2];
    return e;
  }

  /* 防御側特性の倍率と、発動した特性名。かたやぶりなら全て無視する。
     テーブルは配列で持っていて、先頭から順に最初に一致したものを返す（Python と同じ）。 */
  function abilityMod(ability, moveType, moldBreaker, hpFull, isSound, isContact,
                      isPhysical) {
    const ab = ability || '';
    if (moldBreaker) return [1.0, ''];
    for (const table of [R.immuneJa, R.immuneEn]) {
      for (const [name, typ] of table) {
        if (ab.includes(name) && typ === moveType) {
          return [0.0, R.abilityDisplay[name] || name];
        }
      }
    }
    for (const table of [R.halfJa, R.halfEn]) {
      for (const [name, types] of table) {
        if (ab.includes(name) && types.includes(moveType)) {
          return [0.5, R.abilityDisplay[name] || name];
        }
      }
    }
    // もふもふ: ほのおは2倍、それ以外の接触技は0.5倍。両方に当てはまる技は無い
    for (const table of [R.doubleJa, R.doubleEn]) {
      for (const [name, types] of table) {
        if (ab.includes(name) && types.includes(moveType)) return [2.0, 'もふもふ'];
      }
    }
    if (isContact && R.contactHalf.some(k => ab.includes(k))) {
      return [0.5, ab.includes('はどうのぼうご') ? 'はどうのぼうご' : 'もふもふ'];
    }
    // ファーコート: 受ける物理技0.5倍（防御を2倍にして計算するのと同じ）
    if (isPhysical && R.physicalHalf.some(k => ab.includes(k))) return [0.5, 'ファーコート'];
    if ((ab.includes('マルチスケイル') || ab.includes('multiscale')) && hpFull) {
      return [0.5, 'マルチスケイル'];
    }
    if ((ab.includes('ぼうおん') || ab.includes('soundproof')) && isSound) {
      return [0.0, 'ぼうおん'];
    }
    for (const k of ['ハードロック', 'フィルター', 'solid-rock', 'filter', 'prism-armor']) {
      if (ab.includes(k)) return [0.75, 'ハードロック'];
    }
    if (ab.includes('ばけのかわ') || ab.includes('disguise')) return [1.0, 'ばけのかわ'];
    // がんじょう: HP満タンなら必ず1残る。倍率ではなく手数+1として効かせる
    if ((ab.includes('がんじょう') || ab.includes('sturdy')) && hpFull) return [1.0, 'がんじょう'];
    return [1.0, ''];
  }

  // ------------------------------------------------------------ ダメージ

  /* レベル50固定。[最低乱数, 最高乱数] を返す。
     丸めは 基礎 → 急所 → 乱数 → 一致 → 相性 → その他 の順に切り捨てる。順番を変えないこと。
     急所（必ず急所に当たる技）は乱数より前で、基礎ダメージ（+2 まで含めた値）に1.5を掛ける。
     威力を1.5倍する形で代用すると +2 の扱いがずれる。 */
  function damage(power, attack, defense, stab, typeEff, extra, crit) {
    stab = stab === undefined ? 1.0 : stab;
    typeEff = typeEff === undefined ? 1.0 : typeEff;
    extra = extra === undefined ? 1.0 : extra;
    let base = Math.trunc(22 * power * attack / defense / 50) + 2;
    if (crit) base = Math.trunc(base * 1.5);
    const roll = (r) => {
      let x = Math.trunc(base * r);
      x = Math.trunc(x * stab);
      x = Math.trunc(x * typeEff);
      x = Math.trunc(x * extra);
      return Math.max(1, x);
    };
    return [roll(0.85), roll(1.0)];
  }

  /* 連続技の合計ダメージ。1発ずつ damage() を通して足すこと。
     各発で切り捨てが入るので、威力を合算して1回で計算すると数値が合わない。
     何回当たるか（min/max）と威力の増分（step）は技データから導いた結果を使う。 */
  function multiDamage(mh, power, attack, defense, stab, typeEff, extra, skillLink, crit) {
    const total = (hits, idx) => {
      let s = 0;
      for (let i = 0; i < hits; i++) {
        s += damage(power + mh.step * i, attack, defense, stab, typeEff, extra, crit)[idx];
      }
      return s;
    };
    // スキルリンクは必ず最大回数当たるので、最低側も最大回数で数える
    return [total(skillLink ? mh.max : mh.min, 0), total(mh.max, 1)];
  }

  /* おやこあいの合計ダメージ。2発目は威力1/4。
     連続技と同じく1発ずつ damage() を通す（発ごとに切り捨てが入るため）。 */
  function bondDamage(power, atk, dfn, stab, t, extra, crit) {
    const a = damage(power, atk, dfn, stab, t, extra, crit);
    const b = damage(Math.max(1.0, power / 4), atk, dfn, stab, t, extra, crit);
    return [a[0] + b[0], a[1] + b[1]];
  }

  /* ばけのかわで1回止まるぶん、必要な手数が1つ増えたときの判定。 */
  function verdictPlusOne(v) {
    return R.verdictPlusOne[v] || v;
  }

  function verdict(lo, hi, hp) {
    if (lo >= hp) return '確1';
    if (hi >= hp) return '乱1';
    if (lo * 2 >= hp) return '確2';
    if (hi * 2 >= hp) return '乱2';
    if (lo * 3 >= hp) return '確3';
    return '4発+';
  }

  /* 自分がステルスロックを撒いている場合に相手が受けるダメージ。
     マジックガードは無効。ひこうタイプにも入る（まきびしと違い接地不要）。 */
  function srDamage(threat) {
    const ab = threat.ability || '';
    if (ab === 'magic-guard' || ab.includes('マジックガード')) return 0;
    const t = eff('いわ', threat.types[0], threat.types[1]);
    return Math.trunc(threat.st[0] * t / 8);
  }

  // ------------------------------------------------------------ 自軍→相手

  /* 持ち物によるダメージ補正。[攻撃, その他補正] を返す。
     特性と同じく、自軍の打点にも相手からの被弾にも同じ関数を通すこと。 */
  function itemMods(item, m, moveType, typeEff, atk, extra) {
    const spec = R.itemDamage[item || ''];
    if (!spec) return [atk, extra];
    if (spec.type && spec.type !== moveType) return [atk, extra];
    if (spec.super && typeEff < 2) return [atk, extra];
    if (spec.cat && spec.cat !== m.cat) return [atk, extra];
    if (spec.atk_mult) atk = Math.trunc(atk * spec.atk_mult);
    if (spec.mult) extra *= spec.mult;
    return [atk, extra];
  }

  /* 攻撃側の特性による補正。[技タイプ, 威力, 攻撃, その他補正, 一致補正] を返す。
     **自軍からの打点も相手からの被弾も必ずこれを通すこと。** 片方にだけ書くと
     もう片方が抜ける（実際にてきおうりょくが相手側にしか入っておらず、
     自軍がてきおうりょく持ちだと打点が3割以上低く出ていた）。 */
  function offensiveMods(ability, move, m, attackerTypes, atk, protean, defenderAbility) {
    ability = ability || '';
    let moveType = m.type, power = m.power, extra = 1.0;

    for (const [name, skinType] of Object.entries(R.skinAbilities)) {
      if (ability.includes(name) && moveType === 'ノーマル') {
        moveType = skinType; extra *= 1.2;
        break;
      }
    }
    // メガソーラー: 天候に関わらず自分だけ にほんばれ 状態として扱う
    if (ability.includes('メガソーラー')) {
      if (move === 'ウェザーボール') { moveType = 'ほのお'; power = 100.0; }
      if (moveType === 'ほのお') extra *= 1.5;
      else if (moveType === 'みず') extra *= 0.5;
    }
    // ほのおのたてがみ: ほのお技の威力1.5倍（メガカエンジシ専用）
    if (ability.includes('ほのおのたてがみ') && moveType === 'ほのお') extra *= 1.5;
    // すいほう: 自分のみず技2倍。受けるほのお半減は abilityMod 側
    if (ability.includes('すいほう') && moveType === 'みず') extra *= 2.0;
    // フェアリーオーラ: 場に居る間、攻撃側・防御側どちらが持っていてもフェアリー技が1.33倍
    if (moveType === 'フェアリー'
        && (ability.includes('フェアリーオーラ')
            || (defenderAbility || '').includes('フェアリーオーラ'))) extra *= 1.33;
    if (ability.includes('てつのこぶし') && PUNCH.has(move)) extra *= 1.2;
    // メガランチャー（メガカメックス58位）。技4つすべてが波動技なので影響が大きい
    if (ability.includes('メガランチャー') && PULSE.has(move)) extra *= 1.5;
    if (ability.includes('テクニシャン') && power <= 60) power *= 1.5;
    if ((ability.includes('ちからもち') || ability.includes('ヨガパワー')) && m.cat === '物理') atk *= 2;
    if (ability.includes('きれあじ') && SLASH.has(move)) extra *= 1.5;
    if (ability.includes('かたいツメ') && CONTACT.has(move)) extra *= 1.3;

    let stab;
    if (protean) stab = 1.5;
    else if (ability.includes('てきおうりょく') && attackerTypes.includes(moveType)) stab = 2.0;
    else stab = attackerTypes.includes(moveType) ? 1.5 : 1.0;
    const flags = {
      // おやこあい: 1ターンに2回攻撃。2発目は威力1/4
      parentalBond: ability.includes('おやこあい') && m.cat !== '変化' && !m.multi,
      skillLink: ability.includes('スキルリンク'),
      accMult: ability.includes('ふくがん') ? 1.3 : 1.0,
    };
    return [moveType, power, atk, extra, stab, flags];
  }

  // ------------------------------------------------------------ フィールド
  /* フィールドは「場の状態」で、張った側だけでなく**両者に効く**。
     どの特性がどれを張るか・どの技がどう変わるかの判断は Python 側にあり、
     ここは rules から受け取って掛けるだけ（abilityTypeEffect と同じ分担）。 */

  function terrainOf(...mons) {
    for (const mon of mons) {
      if (!mon) continue;
      const ab = mon.ability || '';
      for (const [k, v] of Object.entries(R.terrainMakers)) {
        if (ab.includes(k)) return v;
      }
    }
    return null;
  }

  /* 接地しているか。フィールドは地上のポケモンにしか効かない。 */
  function isGrounded(types, ability, item) {
    if ((types || []).includes('ひこう')) return false;
    const ab = ability || '';
    if (ab.includes('ふゆう') || ab.includes('levitate')) return false;
    return !(item || '').includes('ふうせん');
  }

  function terrainBlocksPriority(terrain, mon) {
    return terrain === 'サイコ' && isGrounded(mon.types, mon.ability, mon.item);
  }

  /* [技タイプ, 威力, その他補正, 優先度] を返す。Python の terrain_mods と同じ順序で掛ける。 */
  function terrainMods(terrain, move, moveType, power, extra, pri, atkGrounded, defGrounded) {
    if (!terrain) return [moveType, power, extra, pri];
    const spec = R.terrainMoves[move];
    if (spec && (spec.any || spec.terrain === terrain)) {
      const ok = spec.ground === 'self' ? atkGrounded : defGrounded;
      if (ok) {
        if (spec.retype) moveType = R.terrainType[terrain];
        if (spec.power) power = spec.power;
        if (spec.mult) extra *= spec.mult;
        pri += spec.pri || 0;
      }
    }
    if (atkGrounded && moveType === R.terrainType[terrain]) extra *= R.terrainBoost;
    if (defGrounded) {
      if (terrain === 'グラス' && R.grassHalved.includes(move)) extra *= 0.5;
      else if (terrain === 'ミスト' && moveType === 'ドラゴン') extra *= 0.5;
    }
    return [moveType, power, extra, pri];
  }

  /* タイプが変わると一致補正もやり直しになる（だいちのはどう） */
  function restab(ability, moveType, types) {
    if ((ability || '').includes('てきおうりょく') && types.includes(moveType)) return 2.0;
    return types.includes(moveType) ? 1.5 : 1.0;
  }

  function myHit(member, move, threat, hpEff) {
    if (STATUS.has(move)) return null;
    if (OHKO.has(move)) return { move, ohko: true, acc: MOVES[move].acc };
    const m = MOVES[move];
    if (!m) return null;
    const atk0 = m.cat === '物理' ? member.st[1] : member.st[3];
    // へんげんじざいは場に出て最初の技で発動する。この表は対面した瞬間を見るものなので、
    // 自軍側は発動している前提で計算する（相手側は発動・未発動の2行に分けている）。
    const protean = ['へんげんじざい', 'リベロ'].some(k => (member.ability || '').includes(k));
    // eslint-disable-next-line prefer-const
    let [moveType, power, atk, extra, stab, flags] =
      offensiveMods(member.ability, move, m, member.types, atk0, protean, threat.ability);
    // フィールドは対面の属性。両者の特性から決まり、張った側に関係なく双方に効く
    const terrain = terrainOf(member, threat);
    let pri = m.pri || 0;
    if (terrain) {
      [moveType, power, extra, pri] = terrainMods(
        terrain, move, moveType, power, extra, pri,
        isGrounded(member.types, member.ability, member.item),
        isGrounded(threat.types, threat.ability, threat.item));
      if (!protean) stab = restab(member.ability, moveType, member.types);
    }
    const t = moveEff(move, moveType, threat.types[0], threat.types[1]);
    [atk, extra] = itemMods(member.item, m, moveType, t, atk, extra);
    let [am, abName] = abilityMod(threat.ability, moveType, member.mold_breaker,
                                  threat.hp_full !== false, SOUND_SET.has(move),
                                  CONTACT.has(move), m.cat === '物理');
    if (abName === 'ハードロック' && t < 2) am = 1.0;
    const disguise = (abName === 'ばけのかわ');
    if (disguise) am = 1.0;   // 倍率ではなく1回無効なので、ダメージは等倍のまま
    const sturdy = (abName === 'がんじょう');
    if (sturdy) am = 1.0;     // がんじょうも倍率ではない。手数を1つ増やす形で効かせる

    const dfn = m.cat === '物理' ? threat.st[2] : threat.st[4];
    const hp = hpEff === undefined || hpEff === null ? threat.st[0] : hpEff;

    // タイプ相性か特性で通らない技。damage() は最低1を返すので、そのまま計算すると
    // 「ふゆう持ちにじしんが1ダメージ」のような、実際には起きない数字が出てしまう。
    if (t * am === 0) {
      const res0 = { move, lo: 0, hi: 0, pl: 0, ph: 0, eff: t,
                     verdict: '4発+', nullified: true };
      if (abName) { res0.ab_name = abName; res0.ab_mult = am; }
      return res0;
    }

    // 特性の倍率は「その他補正」に入れる。相性と掛け合わせてから1回で切り捨てると、
    // 段階を分けた場合と結果がずれる（ハードロックの0.75倍で実際にずれる）。
    // 必ず急所に当たる技（トリックフラワーなど）は基礎ダメージが1.5倍になる
    const crit = !!m.crit;
    const [lo, hi] = m.multi
      ? multiDamage(m.multi, power, atk, dfn, stab, t, extra * am, flags.skillLink, crit)
      : (flags.parentalBond
        ? bondDamage(power, atk, dfn, stab, t, extra * am, crit)
        : damage(power, atk, dfn, stab, t, extra * am, crit));

    let v = verdict(lo, hi, hp);
    if (disguise) v = verdictPlusOne(v);   // 皮で1回止まるぶん手数が増える
    // がんじょうは満タンから必ず1残る。確1のときだけ手数が1つ増える
    if (sturdy && lo >= hp) v = verdictPlusOne(v);

    const res = {
      move, lo, hi,
      pl: pyRound(lo * 100 / hp), ph: pyRound(hi * 100 / hp),
      eff: t, verdict: v,
    };
    if (disguise) res.disguise = true;
    if (m.multi) res.hits = m.multi.label;
    if (flags.parentalBond) res.hits = '2回(おやこあい)';
    if (sturdy) res.sturdy = true;
    if (crit) res.crit = true;
    // 優先度はフィールドで変わる（グラススライダー）。素の m.pri ではなく調整後を返す。
    // サイコフィールドは接地した相手への先制技を止めるので、優先度そのものを消す
    if (terrainBlocksPriority(terrain, threat) && pri > 0) { res.pri_blocked = true; pri = 0; }
    if (pri) res.pri = pri;
    if (terrain) res.terrain = terrain;
    if (am !== 1.0 && abName) { res.ab_name = abName; res.ab_mult = am; }
    const acc = m.acc && Math.min(100.0, m.acc * flags.accMult);
    if (acc && acc < 100) res.acc = pyRound(acc);
    return res;
  }

  /* ランク補正の倍率。+n は (2+n)/2。 */
  function rankMultiplier(stages) {
    return stages >= 0 ? (2 + stages) / 2 : 2 / (2 - stages);
  }

  /* 積み技を1回使った後の最大打点。
     上がるのはその技が実際に上げる能力だけで、段階もその技のぶん
     （つるぎのまいは攻撃+2なので2.0倍）。どの技が何段階上げるかは
     技データから導いた rules.boostStages を引く。JS側で解析し直さない。 */
  function boostedHit(member, threat, hpEff) {
    const move = member.boosting_move;
    if (!move) return null;
    const boost = R.boostStages[move];
    if (!boost || !Object.keys(boost).length) return null;
    const boosted = Object.assign({}, member);
    boosted.st = member.st.slice();
    for (const [stat, idx] of [['atk', 1], ['spa', 3]]) {
      if (boost[stat] !== undefined) {
        boosted.st[idx] = Math.trunc(member.st[idx] * rankMultiplier(boost[stat]));
      }
    }
    const hits = member.moves.map(mv => myHit(boosted, mv, threat, hpEff))
                             .filter(h => h && !h.ohko);
    if (!hits.length) return null;
    const best = hits.reduce((a, b) => (b.hi > a.hi ? b : a));
    best.stages = Math.max(...Object.values(boost));
    return best;
  }

  /* 主表示する技と次善の技。判定が最も良いものを主にする。
     同じ確1なら先制技を優先する（素早さに関係なく先に倒せるので価値が違う）。
     そのうえで同条件ならデメリットのない技を優先。 */
  function chooseMove(hits) {
    const attacks = hits.filter(h => h && !h.ohko);
    if (!attacks.length) return [null, null];
    const rank = h => R.verdictRank[h.verdict] || 0;
    const first = h => (h.verdict === '確1' && (h.pri || 0) > 0) ? 0 : 1;
    const sorted = attacks.slice().sort((a, b) =>
      (rank(b) - rank(a)) ||
      (first(a) - first(b)) ||
      ((DRAWBACK.has(a.move) ? 1 : 0) - (DRAWBACK.has(b.move) ? 1 : 0)) ||
      (b.lo - a.lo));
    const primary = sorted[0];
    let alt = null;
    for (const m of sorted.slice(1)) {
      if (m.verdict !== primary.verdict || DRAWBACK.has(m.move) || DRAWBACK.has(primary.move)) {
        alt = m;
        break;
      }
    }
    return [primary, alt];
  }

  // ------------------------------------------------------------ 相手→自軍

  /* 相手の最大打点。採用率が閾値を超える技の中から選び、低採用の技が上回るときだけ
     rare として添える。相手の攻撃特性と自軍の防御特性の両方を反映する。

     条件で剥がれる特性:
       マルチスケイル … 主表示は満タン時（半減）、剥がれた後を stripped に入れて併記。
       ばけのかわ     … 皮がある間は攻撃が通らない。0%を出しても役に立たないので、
                        主表示は剥がれた後の数字にして disguise の印を付ける。
     相手がかたやぶり系ならどちらも無視される。 */
  function theirHit(threat, member) {
    const ability = threat.ability_ja || threat.ability || '';
    const mold = ['かたやぶり', 'ターボブレイズ', 'テラボルテージ'].some(k => ability.includes(k));
    const myAb = member.ability || '';
    const hasMs = myAb.includes('マルチスケイル') && !mold;
    const hasDisguise = myAb.includes('ばけのかわ') && !mold;

    if (hasDisguise) {
      const best = theirHitScan(threat, member, ability, mold, false);
      if (best.move !== '—') best.disguise = true;
      return best;
    }
    const best = theirHitScan(threat, member, ability, mold, true);
    if (hasMs && best.move !== '—') {
      const stripped = theirHitScan(threat, member, ability, mold, false);
      if (stripped.move !== '—' && stripped.hi > best.hi) {
        best.stripped = stripped;
        best.stripped_label = 'マルチスケイル解除';
      }
    }
    return best;
  }

  /* theirHit の本体。自軍の防御特性を効かせるかどうかを切り替えて2回呼ぶ。 */
  function theirHitScan(threat, member, ability, mold, defenderAbilityOn) {
    const main = [], rare = [];
    let defenderSturdy = false;
    const terrain = terrainOf(threat, member);
    for (const entry of threat.moves.slice(0, 8)) {
      const mv = entry.name, usage = entry.usage;
      const m = MOVES[mv];
      if (!m || !m.power) continue;

      const atk0 = m.cat === '物理' ? threat.st[1] : threat.st[3];
      let [moveType, power, atk, extra, stab, flags] =
        offensiveMods(ability, mv, m, threat.types, atk0, threat.protean,
                      defenderAbilityOn ? member.ability : '');

      // 打点側（myHit）と同じフィールド補正を必ず通す。
      // 片方だけに書くと、相手のワイドフォースが威力80のままになる
      let pri = m.pri || 0;
      if (terrain) {
        [moveType, power, extra, pri] = terrainMods(
          terrain, mv, moveType, power, extra, pri,
          isGrounded(threat.types, threat.ability, threat.item),
          isGrounded(member.types, member.ability, member.item));
        if (!threat.protean) stab = restab(ability, moveType, threat.types);
      }

      const t = moveEff(mv, moveType, member.types[0], member.types[1]);
      [atk, extra] = itemMods(threat.item, m, moveType, t, atk, extra);

      // 自軍の防御特性。あついしぼう・ふゆう・マルチスケイルなどが効く。
      // ばけのかわ・がんじょうは倍率ではないのでここでは触らず、呼び出し側で扱う。
      let am = 1.0;
      if (defenderAbilityOn) {
        let abName;
        [am, abName] = abilityMod(member.ability, moveType, mold, true,
                                  SOUND_SET.has(mv), CONTACT.has(mv), m.cat === '物理');
        if (abName === 'ハードロック' && t < 2) am = 1.0;
        if (abName === 'ばけのかわ' || abName === 'がんじょう') {
          am = 1.0;
          if (abName === 'がんじょう') defenderSturdy = true;
        }
      }

      if (t * am === 0) continue;   // 相性か特性で通らない技。damage() は最低1を返すので落とす
      const dfn = m.cat === '物理' ? member.st[2] : member.st[4];
      // 特性の倍率は myHit と同じく「その他補正」に入れる（相性とは段階を分ける）
      const [lo, hi] = m.multi
        ? multiDamage(m.multi, power, atk, dfn, stab, t, extra * am, flags.skillLink, !!m.crit)
        : (flags.parentalBond
          ? bondDamage(power, atk, dfn, stab, t, extra * am, !!m.crit)
          : damage(power, atk, dfn, stab, t, extra * am, !!m.crit));
      const cand = {
        move: mv, lo, hi, usage,
        pl: pyRound(lo * 100 / member.st[0]),
        ph: pyRound(hi * 100 / member.st[0]),
      };
      if (m.multi) cand.hits = m.multi.label;
      if (flags.parentalBond) cand.hits = '2回(おやこあい)';
      if (m.crit) cand.crit = true;
      // サイコフィールドは接地したこちらへの先制技を止める
      if (terrainBlocksPriority(terrain, member) && pri > 0) { cand.pri_blocked = true; pri = 0; }
      if (pri) cand.pri = pri;
      if (terrain) cand.terrain = terrain;
      (usage > R.rareMoveThreshold ? main : rare).push(cand);
    }
    const pool = main.length ? main : rare;
    if (!pool.length) return { move: '—', lo: 0, hi: 0, pl: 0, ph: 0 };
    // がんじょう: 満タンから受けるぶんは必ず1残る。呼び出し側が手数+1にする
    if (defenderSturdy) for (const c of pool) c.sturdy = true;
    let best = pool.reduce((a, b) => (b.hi > a.hi ? b : a));
    // 先制技で落とされるなら、素早さで勝っていても行動前に倒される。
    // 他にもっとダメージの大きい技があっても、こちらを主表示にする。
    const ko = pool.filter(c => (c.pri || 0) > 0 && c.hi >= member.st[0]);
    if (ko.length && (best.pri || 0) <= 0) {
      best = ko.reduce((a, b) => (b.hi > a.hi ? b : a));
    }
    if (main.length && rare.length) {
      const topRare = rare.reduce((a, b) => (b.hi > a.hi ? b : a));
      if (topRare.hi > best.hi) best = Object.assign({}, best, { rare: topRare });
    }
    return best;
  }

  // ------------------------------------------------------------ 処理判定
  /* 「処理できる」の定義:
       ① 先手（素早さ上、または先制技）を取っており、1発で倒せる
       ② 後手だが、相手の最大打点を耐えて倒せる
       ③ 先手後手に関わらず、ターン制の打ち合いで先に相手を倒せる
     ①②は③の特殊ケースなので、実装は③のレースに一本化してある。
     乱数はこちらに不利な側で固定する（自分は最低乱数、相手は最高乱数）。
     そうしないと「高乱数を引けば勝てる」相手まで処理できる扱いになってしまう。

     build/generate.py の process_check からの移植。**片方だけ直さないこと。**
     appdata/golden.json の processed 欄で全件突き合わせている。 */

  /* [回復技1回ぶんの回復量, たべのこしの毎ターン回復量]。
     回復技はそのターン攻撃できない。たべのこしはターンを消費しない。 */
  function healParts(mon, movesUse, terrain) {
    const hp = mon.st[0];
    const recovery = new Set(R.recoveryMoves);
    const names = movesUse
      ? movesUse.filter(e => e.usage > R.rareMoveThreshold).map(e => e.name)
      : (mon.moves || []);
    const moveHeal = names.some(n => recovery.has(n)) ? Math.floor(hp / 2) : 0;
    let passive = (mon.item || '').includes('たべのこし') ? Math.floor(hp / 16) : 0;
    // グラスフィールドは接地しているポケモンを毎ターン1/16回復する（たべのこしと同じ枠）
    if (terrain === 'グラス' && isGrounded(mon.types, mon.ability, mon.item)) {
      passive += Math.floor(hp / 16);
    }
    return [moveHeal, passive];
  }

  /* 1発目 firstDmg、2発目以降 restDmg で倒すのに要するターン数。倒せないなら null。
     マルチスケイルのように満タンのときだけ効く特性があるので、初撃を分けている。 */
  function turnsToKo(hp, firstDmg, restDmg, extraTurns) {
    extraTurns = extraTurns || 0;
    const left = hp - firstDmg;
    if (left <= 0) return 1 + extraTurns;
    if (restDmg <= 0) return null;
    const n = 1 + Math.ceil(left / restDmg) + extraTurns;
    return n <= R.maxTurns ? n : null;
  }

  /* 回復技を挟みながら生き残れるか。n ターンに1回だけ回復して残り n-1 ターン攻撃できる、
     その n を返す。支えきれないなら null、そもそも削られないなら 0。 */
  function sustainCycle(hpHeal, passive, incoming) {
    const net = incoming - passive;
    if (net <= 0) return 0;              // たべのこしだけで足りる
    if (hpHeal <= 0) return null;
    const n = Math.floor(hpHeal / net) + 1;
    return n >= 2 ? n : null;            // n=1 は「毎ターン回復＝攻撃できない」
  }

  /* この駒がこの相手を処理できるか。{ok, why, turns, move, first, takePh, sup} を返す。
     first / takePh / sup は表示用の材料（★を付けるため）で、判定には使わない。

     回復技はそのターン攻撃できない。これを踏まえると相手の最適行動は二択になる:
       ・回復量 >= こちらの打点 なら、毎ターン回復すれば永久に落ちない → 処理不可
       ・回復量 < こちらの打点 なら、回復するほど攻撃ターンを失って損 → 一度も回復しない */
  function processCheck(member, threat) {
    const back = theirHit(threat, member);
    const theirDmg = back.hi;                    // 相手は最高乱数
    const theirPri = back.pri || 0;
    const myHp = member.st[0], theirHp = threat.st[0];
    // グラスフィールドは両者を回復させる。**片方だけに渡さないこと。**
    const terrain = terrainOf(member, threat);
    const [myHeal, myPass] = healParts(member, undefined, terrain);
    const [theirHeal, theirPass] = healParts(threat, threat.moves, terrain);

    // 2発目以降は相手が満タンではない。マルチスケイル・がんじょうは初撃にしか効かない
    const threatHurt = Object.assign({}, threat, { hp_full: false });

    let best = null;
    for (const mv of member.moves) {
      const h = myHit(member, mv, threat);
      if (!h || h.ohko || !h.hi) continue;       // 一撃必殺は運任せなので数えない
      const h2 = myHit(member, mv, threatHurt) || h;
      const firstDmg = h.lo;                     // 自分は最低乱数
      const restDmg = h2.lo;
      // 相手が回復技を撃ち続けて耐えきれるなら、この技では永久に落とせない
      if (theirHeal && theirHeal + theirPass >= firstDmg) continue;
      const extra = (h.sturdy || h.disguise) ? 1 : 0;
      let myTurns = turnsToKo(theirHp, firstDmg - theirPass, restDmg - theirPass, extra);
      if (myTurns === null) continue;
      if (DRAWBACK.has(mv)) myTurns = myTurns * 2 - 1;   // 反動で次のターン動けない

      const cycle = sustainCycle(myHeal, myPass, theirDmg);
      let theirTurns;
      if (cycle === 0) {
        theirTurns = null;                       // そもそも削られない
      } else if (cycle) {
        theirTurns = null;
        myTurns = Math.ceil(myTurns * cycle / (cycle - 1));
        if (myTurns > R.maxTurns) continue;
      } else {
        theirTurns = turnsToKo(myHp, theirDmg - myPass, theirDmg - myPass);
      }
      const pri = h.pri || 0;
      const first = pri > theirPri || (pri === theirPri && member.speed > threat.speed);
      let ok;
      if (theirTurns === null) ok = true;
      else if (first) ok = myTurns <= theirTurns;
      else ok = myTurns < theirTurns;
      if (ok && (best === null || myTurns < best.turns)) {
        best = {
          turns: myTurns, move: mv, first,
          why: (first && myTurns === 1) ? '先手1発'
            : myTurns === 1 ? '後手だが耐えて1発'
              : `打ち合い${myTurns}ターン`,
        };
      }
    }
    const takePh = back.ph;
    if (best) {
      // 超有利かどうかは「1発で倒せる」ことが前提。そのうえで先手を取っているか、
      // 後手でも返しが軽いか。境目は Python 側の SUPER_TAKE_PH
      return {
        ok: true, move: best.move, why: best.why, turns: best.turns,
        first: best.first, takePh,
        sup: best.turns === 1 && (best.first || takePh <= R.superTakePh),
      };
    }
    return { ok: false, move: null, why: '', turns: null, first: false, takePh, sup: false };
  }

  // ------------------------------------------------------------ パーティの解析

  const STAT_KEYS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
  const STAT_LABELS = ['H', 'A', 'B', 'C', 'D', 'S'];

  class PartyError extends Error {}

  function natureJaToEn(ja) {
    for (const [en, name] of Object.entries(R.natureJa)) if (name === ja) return en;
    return null;
  }

  /* 実数値から能力ポイントを逆算する。1ポイントで実数値がちょうど1上がるので解は一意。
     合わないときは黙って近い値を採らずエラーにする。 */
  function findPoints(base, target, isHp, mult, label, who) {
    const searchMax = R.maxPointsPerStat + 20;
    const matches = [];
    for (let p = 0; p <= searchMax; p++) {
      if (statValue(base, p, isHp, mult) === target) matches.push(p);
    }
    if (!matches.length) {
      const reach = [];
      for (let p = 0; p <= R.maxPointsPerStat; p++) {
        const v = statValue(base, p, isHp, mult);
        if (!reach.includes(v)) reach.push(v);
      }
      throw new PartyError(
        `${who}: ${label}の実数値${target}になる能力ポイントがありません。` +
        `0〜${R.maxPointsPerStat}ポイントで取りうる値: ${reach.sort((a, b) => a - b).join(', ')}`);
    }
    const p = matches[0];
    if (p > R.maxPointsPerStat) {
      throw new PartyError(
        `${who}: ${label}の実数値${target}にはポイント${p}が必要ですが、` +
        `1ステータスの上限${R.maxPointsPerStat}を超えています。`);
    }
    return p;
  }

  function evPoints(base, targets, natureEn, who) {
    const points = [];
    for (let i = 0; i < 6; i++) {
      const isHp = i === 0;
      const mult = isHp ? 1 : natMult(natureEn, STAT_KEYS[i]);
      points.push(findPoints(base[i], targets[i], isHp, mult, STAT_LABELS[i], who));
    }
    const total = points.reduce((a, b) => a + b, 0);
    if (total > R.maxPointsTotal) {
      const breakdown = STAT_LABELS.map((l, i) => l + points[i]).join(' ');
      throw new PartyError(
        `${who}: 能力ポイントの合計が${total}で、上限${R.maxPointsTotal}を超えています。（内訳 ${breakdown}）`);
    }
    return points;
  }

  /* 実数値から能力ポイントを逆算する。party.txt の取り込みで使う。
     1ポイントで実数値がちょうど1上がるので解は一意。合わなければ PartyError。 */
  function pointsFromStats(speciesName, natureEn, targets) {
    const dex = DEX[speciesName];
    if (!dex) throw new PartyError(`ポケモン名「${speciesName}」が図鑑に見つかりません。`);
    return evPoints(dex.base, targets, natureEn, speciesName);
  }

  function abilityFlags(ability) {
    return {
      mold_breaker: R.moldBreakerAbilities.includes(ability),
      fairy_skin: R.fairySkinAbilities.includes(ability),
      sharpness: R.sharpnessAbilities.includes(ability),
    };
  }

  function makeMember(id, name, form, species, ev, natureEn, ability, item, moves, scarf) {
    const f = abilityFlags(ability);
    const dex = DEX[species];
    const st = stats(dex.base, ev, natureEn);
    return {
      id, name, form, species, ev: ev.slice(), nature: natureEn,
      ability, item, moves: moves.slice(), scarf,
      mold_breaker: f.mold_breaker, fairy_skin: f.fairy_skin, sharpness: f.sharpness,
      life_orb: item === 'いのちのたま',
      boosting_move: moves.find(mv => BOOSTING.has(mv)) || null,
      st, types: [dex.t1, dex.t2],
      speed: scarf ? Math.trunc(st[5] * 1.5) : st[5],
    };
  }

  /* party.txt を読んでメンバー一覧にする。1体4行・空行区切り・# はコメント。
     持ち物がメガストーンなら「メガ」「非メガ」の2件に増やす。能力ポイントは
     メガ前の実数値から逆算した値をそのまま使い、種族値だけメガ側に差し替える。 */
  function parseParty(text) {
    const blocks = [];
    let cur = [];
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (line.startsWith('#')) continue;
      if (!line) { if (cur.length) { blocks.push(cur); cur = []; } continue; }
      cur.push(line);
    }
    if (cur.length) blocks.push(cur);
    if (!blocks.length) throw new PartyError('パーティが1体も見つかりません。');

    const members = [];
    blocks.forEach((lines, idx) => {
      const bi = idx + 1;
      let who = `${bi}体目`;
      if (lines.length !== 4) {
        throw new PartyError(`${who}: 1体は4行のはずが${lines.length}行あります。`);
      }
      const [l1, l2, l3, l4] = lines;

      if (!l1.includes(' @ ')) {
        throw new PartyError(`${who}: 1行目は「ポケモン名 @ 持ち物」の形式にしてください。`);
      }
      const [name, item] = l1.split(' @ ').map(s => s.trim());
      who = `${name}（${bi}体目）`;
      if (!DEX[name]) throw new PartyError(`${who}: ポケモン名「${name}」が図鑑に見つかりません。`);

      if (!l2.includes(' / ')) {
        throw new PartyError(`${who}: 2行目は「性格 / 特性」の形式にしてください。`);
      }
      const [natureJa, ability] = l2.split(' / ').map(s => s.trim());
      const natureEn = natureJaToEn(natureJa);
      if (!natureEn) throw new PartyError(`${who}: 性格「${natureJa}」が分かりません。`);
      const baseAb = DEX[name].ab || '';
      if (!baseAb.includes(ability)) {
        throw new PartyError(
          `${who}: 特性「${ability}」が${name}の特性データに見つかりません（データ上の特性: ${baseAb}）。`);
      }

      const parts = l3.split('-');
      if (parts.length !== 6 || !parts.every(p => /^\d+$/.test(p.trim()))) {
        throw new PartyError(`${who}: 3行目は実数値 H-A-B-C-D-S の形式にしてください。`);
      }
      const targets = parts.map(p => parseInt(p, 10));

      const moves = l4.split(' / ').map(s => s.trim()).filter(Boolean);
      if (!moves.length || moves.length > 4) {
        throw new PartyError(`${who}: 技は1〜4個にしてください。`);
      }
      for (const mv of moves) {
        if (!MOVES[mv]) throw new PartyError(`${who}: 技「${mv}」が技データに見つかりません。`);
      }

      const ev = evPoints(DEX[name].base, targets, natureEn, who);
      const megaName = 'メガ' + name;
      const hasMega = DEX[megaName] && DEX[megaName].mega && item.includes('ナイト');
      const tag = String(bi).padStart(2, '0');

      if (hasMega) {
        members.push(makeMember(`p${tag}_mega`, name, 'メガ', megaName, ev, natureEn,
                                DEX[megaName].ab, item, moves, false));
        members.push(makeMember(`p${tag}_base`, name, '非メガ', name, ev, natureEn,
                                ability, '—', moves, false));
      } else {
        const form = item === 'こだわりスカーフ' ? 'スカーフ' : '';
        members.push(makeMember(`p${tag}`, name, form, name, ev, natureEn,
                                ability, item, moves, item === 'こだわりスカーフ'));
      }
    });
    return members;
  }

  /* メンバー一覧を party.txt 形式に戻す。メガ／非メガは1体にまとめ直す。 */
  function formatParty(entries) {
    return entries.map(e =>
      `${e.name} @ ${e.item}\n` +
      `${e.natureJa} / ${e.ability}\n` +
      `${e.stats.join('-')}\n` +
      `${e.moves.join(' / ')}`
    ).join('\n\n') + '\n';
  }

  // ------------------------------------------------------------ 自己検証

  /* appdata/golden.json（Python が計算した期待値）と突き合わせる。
     数字が1でもずれたら移植のどこかが壊れている。 */
  function selfTest(golden, threats) {
    const members = parseParty(golden.partyText);
    const issues = [];

    const byId = {};
    members.forEach(m => { byId[m.id] = m; });
    golden.party.forEach(p => {
      const m = byId[p.id];
      if (!m) { issues.push(`メンバー ${p.id} が作られていない`); return; }
      if (JSON.stringify(m.st) !== JSON.stringify(p.st)) {
        issues.push(`${p.name}${p.form} の実数値: 期待 ${p.st} / 実際 ${m.st}`);
      }
      if (JSON.stringify(m.ev) !== JSON.stringify(p.ev)) {
        issues.push(`${p.name}${p.form} の能力ポイント: 期待 ${p.ev} / 実際 ${m.ev}`);
      }
    });

    // 文字列コード。Python が作ったコードを復元して、同じパーティに戻るか。
    // さらに再符号化して同じ文字列になるか（JS側の符号化も突き合わせる）。
    if (typeof PartyCode !== 'undefined' && PartyCode.ready && golden.partyCode) {
      try {
        const back = parseParty(PartyCode.decode(golden.partyCode, DEX, R));
        const want = members.map(m => [m.name, m.form, m.item, m.ability,
          m.nature, m.ev.join(','), m.moves.join('/')].join('|'));
        const got = back.map(m => [m.name, m.form, m.item, m.ability,
          m.nature, m.ev.join(','), m.moves.join('/')].join('|'));
        if (want.join('|') !== got.join('|')) {
          issues.push('文字列コードから復元したパーティが party.txt と違う');
        }
        const again = PartyCode.encodeMembers(members, DEX, R);
        if (again !== golden.partyCode) {
          issues.push(`文字列コードがPython版と違う: 期待 ${golden.partyCode} / 実際 ${again}`);
        }
      } catch (e) {
        issues.push('文字列コードの検証で例外: ' + e.message);
      }
    }

    let checked = 0;
    for (const row of golden.rows) {
      const t = threats[row.threat];
      const m = byId[row.member];
      if (!m) continue;
      const hits = m.moves.map(mv => myHit(m, mv, t));
      const [primary] = chooseMove(hits);
      if (!primary) { issues.push(`${t.name}/${row.member}: 主表示が出ない`); continue; }
      const back = theirHit(t, m);
      const sr = srDamage(t);
      const hpSr = Math.max(t.st[0] - sr, 1);
      const hitsSr = m.moves.map(mv => myHit(m, mv, t, hpSr));
      const [primarySr] = chooseMove(hitsSr);
      const boosted = boostedHit(m, t);

      const cmp = [
        ['move', primary.move, row.move], ['lo', primary.lo, row.lo],
        ['hi', primary.hi, row.hi], ['verdict', primary.verdict, row.verdict],
        ['pl', primary.pl, row.pl], ['ph', primary.ph, row.ph],
        ['srVerdict', primarySr ? primarySr.verdict : null, row.srVerdict],
        ['srMove', primarySr ? primarySr.move : null, row.srMove],
        ['backMove', back.move, row.backMove], ['backPh', back.ph, row.backPh],
        ['backRare', back.rare ? back.rare.move : null, row.backRare],
        ['backStripped', back.stripped ? back.stripped.ph : null, row.backStripped],
        ['backDisguise', !!back.disguise, row.backDisguise],
        ['primaryDisguise', !!primary.disguise, row.primaryDisguise],
        ['primaryHits', primary.hits === undefined ? null : primary.hits, row.primaryHits],
        ['processed', processCheck(m, t).ok, row.processed],
        ['processSuper', processCheck(m, t).sup, row.processSuper],
        ['primaryPri', primary.pri === undefined ? null : primary.pri, row.primaryPri],
        ['backPri', back.pri === undefined ? null : back.pri, row.backPri],
        ['terrain', primary.terrain === undefined ? null : primary.terrain, row.terrain],
        ['boostMove', boosted ? boosted.move : null, row.boostMove],
        ['boostPh', boosted ? boosted.ph : null, row.boostPh],
        ['boostStages', boosted ? boosted.stages : null, row.boostStages],
        ['srDamage', sr, row.srDamage],
      ];
      for (const [field, got, want] of cmp) {
        checked++;
        if (got !== want) {
          issues.push(`${t.name}[${row.threat}]/${row.member} ${field}: 期待 ${want} / 実際 ${got}`);
        }
      }
    }
    return { checked, issues };
  }

  return {
    load, stats, statValue, eff, abilityMod, damage, verdict, srDamage,
    myHit, boostedHit, theirHit, chooseMove, processCheck,
    terrainOf, isGrounded,
    parseParty, formatParty, selfTest, pyRound, PartyError, pointsFromStats,
    get dex() { return DEX; },
    get moves() { return MOVES; },
    get rules() { return R; },
  };
})();
