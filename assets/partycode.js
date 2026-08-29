/* パーティを1本の文字列コードにする／から戻す。build/partycode.py からの移植。
 *
 * party.txt は今までどおり一次データで、これはその持ち運び用の別表現。
 *
 * パーティ全体を1つの多倍長整数（BigInt）にして、2370種類の文字で書き下す。
 * 項目ごとに必要な通り数（基数）が違うので、ビット単位で切り上げず
 * `値 = 値 × 基数 + 数字` で詰める。
 *
 * **Python 版と同時に直すこと。** 片方だけ直すと、ブラウザで作ったコードが
 * Python で読めなくなる。文字集合・台帳・能力ポイントの表はどれも
 * appdata/code.json で Python から受け取っていて、こちらでは定義しない。
 */
'use strict';

const PartyCode = (() => {
  let C = null;              // appdata/code.json
  let INDEX = null;          // 文字 -> 値
  let EV_TOTAL = 0;

  function load(code) {
    C = code;
    INDEX = new Map();
    for (let i = 0; i < C.alphabet.length; i++) INDEX.set(C.alphabet[i], i);
    EV_TOTAL = C.evCount[6][C.maxPointsTotal];
  }

  class CodeError extends Error {}

  // ------------------------------------------------------------ 能力ポイント

  /* 能力ポイント6つ ←→ 0〜EV_TOTAL-1 の通し番号。
     場合の数の表（evCount）は Python が作ったものをそのまま使う。
     同じ漸化式を2箇所に書くと必ずずれる。 */
  function evRank(ev) {
    let r = 0, rem = C.maxPointsTotal;
    for (let i = 0; i < 6; i++) {
      const v = ev[i];
      if (!(v >= 0 && v <= C.maxPointsPerStat)) throw new CodeError(`能力ポイントが範囲外です`);
      if (v > rem) throw new CodeError(`能力ポイントの合計が${C.maxPointsTotal}を超えています`);
      const k = 5 - i;
      for (let x = 0; x < v; x++) r += C.evCount[k][rem - x];
      rem -= v;
    }
    return r;
  }

  function evUnrank(r) {
    const ev = [];
    let rem = C.maxPointsTotal;
    for (let i = 0; i < 6; i++) {
      const k = 5 - i;
      let done = false;
      for (let x = 0; x <= Math.min(C.maxPointsPerStat, rem); x++) {
        const c = C.evCount[k][rem - x];
        if (r < c) { ev.push(x); rem -= x; done = true; break; }
        r -= c;
      }
      if (!done) throw new CodeError('コードの能力ポイントが読めません');
    }
    return ev;
  }

  // ------------------------------------------------------------ 桁の組み立て

  /* (基数, 数字) を**読み出す順**に並べたものを1つの整数にする。
     先頭が最下位になるように、後ろから詰める。 */
  function pack(pairs) {
    let v = 0n;
    for (let i = pairs.length - 1; i >= 0; i--) {
      const [radix, digit] = pairs[i];
      if (!(digit >= 0 && digit < radix)) {
        throw new CodeError(`コードに入らない値です: ${digit} (基数${radix})`);
      }
      v = v * BigInt(radix) + BigInt(digit);
    }
    return v;
  }

  function reader(value) {
    let v = value;
    return {
      take(radix) {
        const r = BigInt(radix);
        const d = Number(v % r);
        v /= r;
        return d;
      },
      get rest() { return v; },
    };
  }

  function toText(value) {
    const base = BigInt(C.alphabet.length);
    if (value === 0n) return C.alphabet[0];
    let out = '';
    while (value > 0n) {
      out = C.alphabet[Number(value % base)] + out;
      value /= base;
    }
    return out;
  }

  function fromText(text) {
    const base = BigInt(C.alphabet.length);
    let v = 0n;
    for (const ch of text) {
      if (/\s/.test(ch)) continue;
      const i = INDEX.get(ch);
      if (i === undefined) throw new CodeError(`コードに使えない文字が入っています: ${ch}`);
      v = v * base + BigInt(i);
    }
    return v;
  }

  // ------------------------------------------------------------ 符号化

  /* entries は party.html が持っている素の入力（name/item/nature/ability/ev/moves）。
     party.txt に書いてある形そのままで、メガ形態には展開されていない。 */
  function monPairs(e, dex) {
    const d = dex[e.name];
    if (!d) throw new CodeError(`図鑑に無いポケモンです: ${e.name}`);
    const pi = C.pokemon.indexOf(e.name);
    if (pi < 0) throw new CodeError(`台帳に無いポケモンです: ${e.name}`);
    const abList = (d.ab_list && d.ab_list.length) ? d.ab_list : [''];
    const ai = abList.indexOf(e.ability);
    if (ai < 0) throw new CodeError(`${e.name} の特性ではありません: ${e.ability}`);
    const ni = C.natures.indexOf(e.nature);
    if (ni < 0) throw new CodeError(`台帳に無い性格です: ${e.nature}`);

    const ii = C.items.indexOf(e.item);
    const pairs = [[C.pokemon.length, pi], [C.natures.length, ni],
      // 特性は「その種が持つ数」を基数にする。1つしか無い種は0桁で済む
      [abList.length, ai],
      [C.items.length + 1, ii < 0 ? C.items.length : ii]];
    if (ii < 0) {
      // 台帳に無い持ち物は生のまま入れる。長くなるが、名前を失うよりよい
      const chars = [...e.item];
      if (chars.length > C.maxItemLen) throw new CodeError(`持ち物の名前が長すぎます: ${e.item}`);
      pairs.push([C.maxItemLen + 1, chars.length]);
      for (const ch of chars) {
        const cp = ch.codePointAt(0);
        if (cp > 0xFFFF) throw new CodeError(`この持ち物はコードにできません: ${e.item}`);
        pairs.push([0x10000, cp]);
      }
    }
    pairs.push([EV_TOTAL, evRank(e.ev)]);
    const moves = e.moves.filter(m => m);
    if (moves.length < 1 || moves.length > 4) throw new CodeError('技は1〜4個にしてください');
    pairs.push([4, moves.length - 1]);
    for (const mv of moves) {
      const mi = C.moves.indexOf(mv);
      if (mi < 0) throw new CodeError(`台帳に無い技です: ${mv}`);
      pairs.push([C.moves.length, mi]);
    }
    return pairs;
  }

  function encode(entries, dex) {
    const mons = entries.filter(e => e && e.name);
    if (mons.length < 1 || mons.length > C.maxParty) {
      throw new CodeError(`コードにできるのは1〜${C.maxParty}体です`);
    }
    let pairs = [[C.maxParty + 1, mons.length]];
    for (const e of mons) pairs = pairs.concat(monPairs(e, dex));
    const body = pack(pairs);
    const mod = BigInt(C.checkMod);
    return toText((body * mod + (body % mod)) * 16n + BigInt(C.version));
  }

  /* コードを party.txt のテキストに戻す。実数値は Engine.stats で計算し直す
     （コードには能力ポイントしか入っていない）。 */
  function decode(text, dex, rules) {
    let value = fromText(text);
    const ver = Number(value % 16n);
    value /= 16n;
    // 1文字違うだけでもここに落ちることが多い。「新しい書式」と決めつけない
    if (ver !== C.version) {
      throw new CodeError('コードが読めません（打ち間違いか、知らない書式です。'
        + `読み取った書式番号 ${ver}、この版は ${C.version}）`);
    }
    const mod = BigInt(C.checkMod);
    const check = value % mod;
    const body = value / mod;
    if (body % mod !== check) {
      throw new CodeError('コードが壊れています（打ち間違いの可能性があります）');
    }

    const natEn = {};
    for (const [en, ja] of Object.entries(rules.natureJa)) natEn[ja] = en;

    const r = reader(body);
    const count = r.take(C.maxParty + 1);
    if (count < 1 || count > C.maxParty) throw new CodeError('コードの体数が読めません');
    const blocks = [];
    for (let i = 0; i < count; i++) {
      const name = pick(C.pokemon, r.take(C.pokemon.length), 'ポケモン');
      const nature = pick(C.natures, r.take(C.natures.length), '性格');
      const d = dex[name];
      const abList = (d.ab_list && d.ab_list.length) ? d.ab_list : [''];
      const ability = abList[r.take(abList.length)];
      const ii = r.take(C.items.length + 1);
      let item;
      if (ii < C.items.length) {
        item = C.items[ii];
      } else {
        const n = r.take(C.maxItemLen + 1);
        item = '';
        for (let k = 0; k < n; k++) item += String.fromCharCode(r.take(0x10000));
      }
      const ev = evUnrank(r.take(EV_TOTAL));
      const nmv = r.take(4) + 1;
      const moves = [];
      for (let k = 0; k < nmv; k++) {
        moves.push(pick(C.moves, r.take(C.moves.length), '技'));
      }
      const st = Engine.stats(d.base, ev, natEn[nature]);
      blocks.push(`${name} @ ${item}\n${nature} / ${ability}\n`
        + st.join('-') + '\n' + moves.join(' / '));
    }
    if (r.rest !== 0n) throw new CodeError('コードに余分な情報が付いています');
    return blocks.join('\n\n') + '\n';
  }

  function pick(list, i, what) {
    if (i >= list.length) {
      throw new CodeError(`この版では読めない${what}が入っています`
        + '（新しいデータで作られたコードかもしれません）');
    }
    return list[i];
  }

  /* Engine.parseParty が返すメンバー配列から符号化する。自己検証で使う。
     parseParty はメガストーン持ちを「メガ」「非メガ」の2件に展開するので、
     Python の collapse() と同じように1件へ戻す。
     **通常形態の名前と特性は非メガ側、メガストーンはメガ側**に入っている。 */
  function encodeMembers(members, dex, rules) {
    const groups = new Map();
    for (const m of members) {
      const key = m.id.split('_')[0];
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(m);
    }
    const entries = [...groups.keys()].sort().map(key => {
      const g = groups.get(key);
      const base = g.find(x => x.form !== 'メガ') || g[0];
      const mega = g.find(x => x.form === 'メガ');
      return {
        name: base.name, item: mega ? mega.item : base.item,
        nature: rules.natureJa[base.nature] || base.nature,
        ability: base.ability, ev: base.ev, moves: base.moves,
      };
    });
    return encode(entries, dex);
  }

  return { load, encode, encodeMembers, decode, CodeError,
    get ready() { return !!C; } };
})();
