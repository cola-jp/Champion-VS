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
  let SLASH, OHKO, STATUS, DRAWBACK, BOOSTING, CONTACT, SOUND_SET;

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

  /* 防御側特性の倍率と、発動した特性名。かたやぶりなら全て無視する。
     テーブルは配列で持っていて、先頭から順に最初に一致したものを返す（Python と同じ）。 */
  function abilityMod(ability, moveType, moldBreaker, hpFull, isSound) {
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
    return [1.0, ''];
  }

  // ------------------------------------------------------------ ダメージ

  /* レベル50固定。[最低乱数, 最高乱数] を返す。
     丸めは 基礎 → 乱数 → 一致 → 相性 → その他 の順に切り捨てる。順番を変えないこと。 */
  function damage(power, attack, defense, stab, typeEff, extra) {
    stab = stab === undefined ? 1.0 : stab;
    typeEff = typeEff === undefined ? 1.0 : typeEff;
    extra = extra === undefined ? 1.0 : extra;
    const base = Math.trunc(22 * power * attack / defense / 50) + 2;
    const roll = (r) => {
      let x = Math.trunc(base * r);
      x = Math.trunc(x * stab);
      x = Math.trunc(x * typeEff);
      x = Math.trunc(x * extra);
      return Math.max(1, x);
    };
    return [roll(0.85), roll(1.0)];
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

  function myHit(member, move, threat, hpEff) {
    if (STATUS.has(move)) return null;
    if (OHKO.has(move)) return { move, ohko: true, acc: MOVES[move].acc };
    const m = MOVES[move];
    if (!m) return null;
    let moveType = m.type, extra = 1.0;
    if (member.fairy_skin && moveType === 'ノーマル') { moveType = 'フェアリー'; extra = 1.2; }
    if (member.sharpness && SLASH.has(move)) extra *= 1.5;
    if (member.life_orb) extra *= 1.3;

    const t = eff(moveType, threat.types[0], threat.types[1]);
    let [am, abName] = abilityMod(threat.ability, moveType, member.mold_breaker,
                                  threat.hp_full !== false, SOUND_SET.has(move));
    if (abName === 'ハードロック' && t < 2) am = 1.0;
    if (abName === 'ばけのかわ') am = 1.0;

    const stab = member.types.includes(moveType) ? 1.5 : 1.0;
    const atk = m.cat === '物理' ? member.st[1] : member.st[3];
    const dfn = m.cat === '物理' ? threat.st[2] : threat.st[4];
    const [lo, hi] = damage(m.power, atk, dfn, stab, t * am, extra);
    const hp = hpEff === undefined || hpEff === null ? threat.st[0] : hpEff;

    const res = {
      move, lo, hi,
      pl: pyRound(lo * 100 / hp), ph: pyRound(hi * 100 / hp),
      eff: t, verdict: verdict(lo, hi, hp),
    };
    if (am !== 1.0 && abName) { res.ab_name = abName; res.ab_mult = am; }
    if (m.acc && m.acc < 100) res.acc = m.acc;
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

  /* 主表示する技と次善の技。判定が最も良いものを主にし、同判定ならデメリットのない技を優先。 */
  function chooseMove(hits) {
    const attacks = hits.filter(h => h && !h.ohko);
    if (!attacks.length) return [null, null];
    const rank = h => R.verdictRank[h.verdict] || 0;
    const sorted = attacks.slice().sort((a, b) =>
      (rank(b) - rank(a)) ||
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
     rare として添える。相手の攻撃特性（最頻のもの）を反映する。 */
  function theirHit(threat, member) {
    const ability = threat.ability_ja || threat.ability || '';
    const main = [], rare = [];
    for (const entry of threat.moves.slice(0, 8)) {
      const mv = entry.name, usage = entry.usage;
      const m = MOVES[mv];
      if (!m || !m.power) continue;

      let moveType = m.type, power = m.power, extra = 1.0;
      let atk = m.cat === '物理' ? threat.st[1] : threat.st[3];

      // メガソーラー: 天候に関わらず自分だけ にほんばれ 状態として扱う
      if (ability.includes('メガソーラー')) {
        if (mv === 'ウェザーボール') { moveType = 'ほのお'; power = 100.0; }
        if (moveType === 'ほのお') extra *= 1.5;
        else if (moveType === 'みず') extra *= 0.5;
      }
      if (ability.includes('テクニシャン') && power <= 60) power *= 1.5;
      if ((ability.includes('ちからもち') || ability.includes('ヨガパワー')) && m.cat === '物理') atk *= 2;
      if (ability.includes('きれあじ') && SLASH.has(mv)) extra *= 1.5;
      if (ability.includes('かたいツメ') && CONTACT.has(mv)) extra *= 1.3;

      let stab;
      if (threat.protean) stab = 1.5;
      else if (ability.includes('てきおうりょく') && threat.types.includes(moveType)) stab = 2.0;
      else stab = threat.types.includes(moveType) ? 1.5 : 1.0;

      const t = eff(moveType, member.types[0], member.types[1]);
      if (t === 0) continue;   // タイプ無効。damage() は最低1を返すので落としておく
      const dfn = m.cat === '物理' ? member.st[2] : member.st[4];
      const [lo, hi] = damage(power, atk, dfn, stab, t, extra);
      const cand = {
        move: mv, lo, hi, usage,
        pl: pyRound(lo * 100 / member.st[0]),
        ph: pyRound(hi * 100 / member.st[0]),
      };
      (usage > R.rareMoveThreshold ? main : rare).push(cand);
    }
    const pool = main.length ? main : rare;
    if (!pool.length) return { move: '—', lo: 0, hi: 0, pl: 0, ph: 0 };
    let best = pool.reduce((a, b) => (b.hi > a.hi ? b : a));
    if (main.length && rare.length) {
      const topRare = rare.reduce((a, b) => (b.hi > a.hi ? b : a));
      if (topRare.hi > best.hi) best = Object.assign({}, best, { rare: topRare });
    }
    return best;
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
    myHit, boostedHit, theirHit, chooseMove,
    parseParty, formatParty, selfTest, pyRound, PartyError,
    get dex() { return DEX; },
    get moves() { return MOVES; },
    get rules() { return R; },
  };
})();
