/* 選出補助。相手のパーティ6体を入れると、1体ずつに対して自分のどの駒が処理できるかを出し、
 * 6体を見渡した推奨選出（3体）まで出す。
 *
 * 処理判定そのものは Engine.processCheck（build/generate.py の process_check の移植）。
 * **ここに勝敗の判定を書き足さないこと。** 書くとダメージ表と食い違う。
 * この画面が持ってよいのは、入力の受け取り・型のまとめ方・選出の組み合わせ探索だけ。
 *
 * 型の扱いがこの画面の肝。使用率データは1体を複数の型に展開していて、相手の型は
 * 対戦前には分からない。だから
 *   すべての型を処理できる → 安定
 *   一部の型だけ処理できる → 条件付き（どの型なら通るかも出す）
 * の2段階に分けている。ここを潰して1つの○×にすると、実戦で外す。
 */
'use strict';

(() => {
  const $ = id => document.getElementById(id);
  const SLOTS = 6;
  let THREATS = [], MEMBERS = [], DEX = {}, R = null;
  let SPECIES = [];          // [{name, rank, rows}] 使用率順→図鑑順。全313体
  let picks = new Array(SLOTS).fill('');
  // メガで見るかどうか。相手も自分も、どちらで見るかは使う人が決める（元のExcelと同じ）。
  // megaOn は自分の枠名 -> true/false、oppForm は相手の種名 -> いま表示している図鑑名。
  const megaOn = {};
  const oppForm = {};

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function label(m) {
    return m.name + (m.form ? `(${m.form})` : '');
  }

  // ---------------------------------------------------------- 名前の照合

  /* 照合用のキー。図鑑名はカタカナだが、実戦では変換前のひらがなのまま打つほうが速い。
     「がぶ」でも ガブリアス が出るように、比べる前に両側をカタカナへ寄せる。
     ひらがな（U+3041〜U+3096）とカタカナ（U+30A1〜U+30F6）は並びが同じなので
     0x60 ずらすだけでよい。NFKC は半角カナ（ｶﾞﾌﾞ）を全角に直すために先に通す。 */
  function fold(s) {
    return (s || '').normalize('NFKC')
      .replace(/[\s　]/g, '')
      .replace(/[ぁ-ゖ]/g, c => String.fromCharCode(c.charCodeAt(0) + 0x60));
  }

  /* さらに表記ゆれを落としたキー。メガ形態は「メガ」付きでも無しでも引けるようにし、
     リージョンフォームの括弧書きも無視する。 */
  function strip(s) {
    return fold(s).replace(/[（(].*?[）)]/g, '').replace(/^メガ/, '');
  }

  /* 一致の強さ。小さいほど強い。0=完全一致 1=前方一致 2=メガ等を外した前方一致 3=部分一致。
     前方一致を部分一致より必ず上に置く。「ガブ」で メガブリガロン が先に出ると使えない。 */
  function matchRank(sp, fq, sq) {
    if (sp.k === fq) return 0;
    if (sp.k.startsWith(fq)) return 1;
    if (sp.ks.startsWith(sq)) return 2;
    if (sp.k.includes(fq) || sp.ks.includes(sq)) return 3;
    return 9;
  }

  function ranked(text) {
    const fq = fold(text);
    if (!fq) return [];
    const sq = strip(text);
    return SPECIES
      .map(s => ({ s, r: matchRank(s, fq, sq) }))
      .filter(x => x.r < 9)
      .sort((a, b) => a.r - b.r || a.s.rank - b.s.rank);
  }

  /* 入力に対する候補。一致の強い順、同じ強さなら使用率順。 */
  function suggest(text) {
    return ranked(text).slice(0, 8).map(x => x.s);
  }

  /* 入力を1体に確定できるか。実戦では数文字しか打たないので、
     前方一致がちょうど1つなら部分一致の候補が他に残っていても確定してよい
     （「ガブ」は ガブリアス で確定。メガブリガロン は部分一致なので邪魔しない）。
     同じ強さの候補が複数あるときは選ばせる。黙って先頭を採らない。 */
  function resolve(text) {
    const list = ranked(text);
    if (!list.length) return null;
    // 最も強い一致の中で1つに決まるならそれ。「ミミ」は ミミッキュ が前方一致で、
    // メガミミロップ は「メガ」を外した前方一致なので弱い。同列に扱うと決まらなくなる。
    const top = list[0].r;
    const strong = list.filter(x => x.r === top);
    return strong.length === 1 ? strong[0].s : null;
  }

  // ---------------------------------------------------------- 駒の枠

  /* メガシンカできるのは1体だけなので、同じ枠のメガ／非メガを1つにまとめて扱う。
     mega と base が両方あるのがメガストーン持ち、plain だけが普通の駒。 */
  function buildSlots(members) {
    const out = [];
    const byName = {};
    for (const m of members) {
      const g = byName[m.name] || (byName[m.name] = { name: m.name });
      if (m.form === 'メガ') g.mega = m;
      else if (m.form === '非メガ') g.base = m;
      else g.plain = m;
      if (!out.includes(g)) out.push(g);
    }
    return out;
  }

  function formOf(slot, useMega) {
    if (slot.plain) return slot.plain;
    return useMega ? slot.mega : slot.base;
  }

  // ---------------------------------------------------------- 判定

  const cache = new Map();

  function check(member, threat) {
    const key = member.id + '\u0000' + threat.rank + threat.name + threat.pattern
      + threat.form + threat.hp_full + threat.protean
      + '/' + (threat.tTerrain || '') + (threat.tWeather || '');
    let v = cache.get(key);
    if (v === undefined) {
      v = Engine.processCheck(member, threat, threat.tTerrain, threat.tWeather);
      cache.set(key, v);
    }
    return v;
  }

  // ------------------------------------------- 味方が張る天気・フィールド

  /* この画面は相手6体を入力するので、**同じパーティに居るかどうかが分かる**。
     ダメージ表は1対1しか見ないので「味方のイエッサンが張っている前提」を出せないが、
     ここでは出せる。グレンアルマのワイドフォースが典型で、自分では張れないが
     イエッサンが同居していれば威力120＋1.3倍になる。

     ただし**張り手を選出してくるとは限らない**ので、片方に決めつけない。
     マルチスケイル解除・へんげんじざい発動と同じく「起こりうる別の状態」として
     行を2つに分け、両方処理できて初めて「安定」にする。 */
  function teamFields(picked) {
    const terrains = new Set(), weathers = new Set();
    for (const sp of picked) {
      const t = sp.rows[0];
      if (!t) continue;
      const te = Engine.terrainOf(t), we = Engine.weatherOf(t);
      if (te) terrains.add(te);
      if (we) weathers.add(we);
    }
    return { terrains: [...terrains], weathers: [...weathers] };
  }

  /* その相手に、その場の状態が実際に影響するか。
     影響しないものまで行に足すと、読む量が倍になるだけで何も分からない。 */
  function affected(sp, members, st) {
    // **1行だけ見る。** 行の違いは配分・マルチスケイル・へんげんじざいで、
    // 「場の状態が効くかどうか」は変わらない。全行回すと描画が3倍遅くなる
    const row = sp.rows[0];
    const alt = Object.assign({}, row, st);
    for (const m of members) {
      const a = Engine.theirHit(row, m);
      const b = Engine.theirHit(alt, m, alt.tTerrain, alt.tWeather);
      if (a.hi !== b.hi || a.move !== b.move) return true;
      for (const mv of m.moves) {
        const ha = Engine.myHit(m, mv, row);
        const hb = Engine.myHit(m, mv, alt, undefined, alt.tTerrain, alt.tWeather);
        if ((ha && ha.hi) !== (hb && hb.hi)) return true;
      }
    }
    return false;
  }

  /* 相手の行を「場の状態」で割り増しする。自分で張る相手は確定しているので割らない。
     割った相手の名前を返す（注意書きに出すため）。 */
  function expandRows(picked, members) {
    // 前回の展開を捨ててから作り直す。入力のたびに増え続けないように
    for (const sp of picked) sp.rows = sp.rows.filter(r => !r.tTerrain && !r.tWeather);
    const { terrains, weathers } = teamFields(picked);
    if (!terrains.length && !weathers.length) return [];
    const split = [];
    for (const sp of picked) {
      if (!sp.rows.length) continue;
      const own = sp.rows[0];
      const states = [];
      if (!Engine.terrainOf(own)) for (const t of terrains) states.push({ tTerrain: t });
      if (!Engine.weatherOf(own)) for (const w of weathers) states.push({ tWeather: w });
      const extra = [];
      for (const st of states) {
        if (!affected(sp, members, st)) continue;
        for (const row of sp.rows) extra.push(Object.assign({}, row, st));
      }
      if (extra.length) {
        sp.rows = sp.rows.concat(extra);
        split.push(sp.name);
      }
    }
    return split;
  }

  /* 行の見出し。使用率データの行は2種類の理由で分かれていて、意味が違う:
       ・配分の型（AS / HB …）… 対戦前には分からない。これが本来の「型」
       ・計算のバリアント（マルチスケイルが剥がれた後 / へんげんじざいの発動有無）
         … 同じ1体の別の状態。型が2つあるわけではない
     両方まとめて「型」と呼ぶと、メガカイリューが「CS型 / CS型」と並んでしまう。 */
  function rowKey(t) {
    let k = t.pattern + (t.form ? `/${t.form}` : '');
    if (t.hp_full === false) k += '・マルチスケイル解除';
    if (t.protean === true) k += '・へんげんじざい発動';
    if (t.protean === false) k += '・不一致技';
    // 味方が張っている前提の行。どちらの状態で通るのか分からないと使えない
    if (t.tTerrain) k += `・${t.tTerrain}フィールド下`;
    if (t.tWeather) k += `・${t.tWeather}`;
    return k;
  }

  /* その駒がその相手（複数の行を持つ）をどこまで見られるか。
     すべての行を処理できて初めて「安定」。剥がれた後のマルチスケイルや
     へんげんじざいの発動も、対戦中に実際に起きる状態なので込みで見る。

     sup（★＝超有利）も同じ考えで、**全部の行が超有利のときだけ**立てる。
     1つの型にだけ強くても対戦前にはどの型か分からないので、目印として使えない。 */
  function verdictFor(member, sp) {
    const okRows = sp.rows.filter(t => check(member, t).ok);
    if (!okRows.length) return { level: 0, share: 0, sup: false };
    const best = okRows
      .map(t => check(member, t))
      .reduce((a, b) => (a.turns <= b.turns ? a : b));
    // 型の%は行ごとではなく型ごとに持っているので、同じ型の行を二重に足さない
    const seen = new Set();
    let share = 0;
    for (const t of okRows) {
      if (seen.has(t.pattern)) continue;
      seen.add(t.pattern);
      share += t.share;
    }
    return {
      level: okRows.length === sp.rows.length ? 2 : 1,
      move: best.move, why: best.why,
      keys: okRows.map(rowKey),      // 条件付きのときは「どの状態なら通るか」が要る
      share,
      sup: okRows.length === sp.rows.length && okRows.every(t => check(member, t).sup),
    };
  }

  // ---------------------------------------------------------- 相性・種族値の表
  /* Excel の「選出補助」シートから移した部分。相手と自分を同じ表に並べて、
     タイプ相性・無補正の種族値・特性を一目で見るためのもの。

     倍率の素の値は appdata/dex.json の eff（Python が相性表から出したもの）。
     タイプ別に効く特性の分だけ rules.abilityTypeEffect を掛ける。
     **どの特性を効かせるかの判断は Python 側にある。** ここでは掛けるだけ。
     特性で変わったセルは括弧付きで出す（ふゆうのじめんなら `(0)`）。 */

  /* 相性の計算に使う特性を1つ決める。どれを使ったかは特性欄で分かるようにする。
     ・自分側 … 登録パーティに書いてある特性。確定している
     ・相手（使用率データあり） … 使用率1位の特性。ツールの他の箇所と同じ
     ・相手（使用率圏外） … 図鑑の特性のうちタイプに効くものを仮定する。
       備える側としては「もらいびかもしれない」前提で見るほうが安全なため。 */
  function abilityForMatrix(dexName, explicit) {
    const tbl = R.abilityTypeEffect;
    // 返すのは「倍率に効いている特性」だけ。効かない特性まで返すと、
    // 特性欄の太字が「これで計算した」の意味を失う（素の倍率なのに太字が付く）
    if (explicit) return tbl[explicit] ? explicit : '';
    const list = (DEX[dexName] && DEX[dexName].ab_list) || [];
    return list.find(a => tbl[a]) || '';
  }

  function effCells(dexName, ability) {
    const d = DEX[dexName];
    const tbl = (ability && R.abilityTypeEffect[ability]) || null;
    return R.typeOrder.map((t, i) => {
      const raw = d.eff[i];
      const mult = tbl && tbl[t] !== undefined ? tbl[t] : 1;
      return { type: t, v: raw * mult, changed: mult !== 1 };
    });
  }

  /* 倍率1つぶんのセル。色は数値で決める（4=赤 2=橙 1=無地 0.5/0.25=水色 0=灰）。
     数字を読まなくても塗りで分かることが、この表の存在意義。 */
  function effCell(c) {
    const v = c.v;
    const cls = v >= 4 ? 'e4' : v >= 2 ? 'e2' : v === 0 ? 'e0'
      : v < 1 ? 'eh' : 'e1';
    const text = Number.isInteger(v) ? String(v) : String(v);
    return `<td class="ef ${cls}">${c.changed ? `(${text})` : text}</td>`;
  }

  function statCells(base) {
    const sorted = [...base].sort((a, b) => b - a);
    const max = sorted[0], second = sorted[1], min = sorted[5];
    return base.map(v => {
      const cls = v === max ? 'b1' : v === second ? 'b2' : v === min ? 'b3' : '';
      return `<td class="bs ${cls}">${v}</td>`;
    }).join('');
  }

  /* この画面だけのタイプ略称。18列を並べるので正式名だと横に伸びすぎる。
     並びは rules.typeOrder（＝ dex.eff の並び）と同じ前提。
     **計算には一切使わない。表示だけ。** 正式名は title 属性に残す。 */
  const TYPE_ABBR = {
    'ノーマル': 'ノ', 'ほのお': '炎', 'みず': '水', 'でんき': '電', 'くさ': '草',
    'こおり': '氷', 'かくとう': '格', 'どく': '毒', 'じめん': '地', 'ひこう': '飛',
    'エスパー': '超', 'むし': '虫', 'いわ': '岩', 'ゴースト': '霊', 'ドラゴン': '竜',
    'あく': '悪', 'はがね': '鋼', 'フェアリー': '妖',
  };

  function abbr(t) {
    return TYPE_ABBR[t] || t;
  }

  function matrixRow(entry) {
    const d = DEX[entry.dexName];
    if (!d) return '';
    const ab = abilityForMatrix(entry.dexName, entry.ability);
    const cells = effCells(entry.dexName, ab);
    // タイプは常に2セル。単タイプでも空セルを置いて、下の相性表の始まる位置を揃える。
    // 色は中の span に付ける。セルを塗ると行の高さに引っ張られて正方形にならない
    const types = [d.t1, d.t2].map(t => t
      ? `<td class="tyc"><span class="tybox" style="--tc:${R.typeColor[t] || '#666'}"` +
        ` title="${esc(t)}">${esc(abbr(t))}</span></td>`
      : '<td class="tyc"></td>').join('');
    // 特性は図鑑の一覧を出す。太字＝倍率に効かせたもの、下線＝持っていれば倍率が変わるもの。
    // どれで計算したか分からないと括弧付きの倍率を読み替えられないし、
    // 「別の特性なら変わる」ことが見えないと マリルリ の あついしぼう を読み落とす
    const abList = (d.ab_list || []).map(a =>
      a === ab ? `<b>${esc(a)}</b>`
        : R.abilityTypeEffect[a] ? `<u>${esc(a)}</u>` : esc(a)).join('/') || '—';
    const [h, , b, , dd] = d.base;
    // 相性はタイプのすぐ右。幅が行ごとに変わらない列（名前・タイプ2つ）だけを前に置くので、
    // 相手の表と自分の表で相性の始まる位置がずれない。特性は幅が大きく変わるので後ろ。
    return `<tr>${entry.head}` + types +
      cells.map(effCell).join('') +
      `<td class="ab">${abList}</td>` + statCells(d.base) +
      // 小数第2位まで。1桁に丸めると ドリュウズ 7.15 が 7.2 になって、
      // 近い駒どうしの並び順が読めなくなる
      `<td class="bulk">${+(h * b / 1000).toFixed(2)}</td>` +
      `<td class="bulk">${+(h * dd / 1000).toFixed(2)}</td></tr>`;
  }

  /* 相手と自分を**1つの表**にまとめる。表を分けると列幅が別々に決まって、
     相性表の始まる位置が上下でずれる（実際にずれて読みにくかった）。
     相手／自分の見出しは、全列をまたぐ行として途中に挟む。 */
  const MTX_COLS = 1 + 2 + 18 + 1 + 6 + 2;

  function matrixTable(groups) {
    const shown = groups.filter(g => g.rows.length);
    if (!shown.length) return '';
    const head = R.typeOrder.map(t =>
      `<th class="ty" style="--tc:${R.typeColor[t] || '#666'}" title="${esc(t)}">` +
      `${esc(abbr(t))}</th>`).join('');
    const body = shown.map(g =>
      `<tr class="mgrp"><td colspan="${MTX_COLS}">` +
      // 横にスクロールしても「相手／自分」が見えるように、中身だけ左に貼り付ける
      `<span class="mgrplbl">${esc(g.title)}</span></td></tr>` + g.rows.join('')
    ).join('');
    return `<div class="mtxwrap"><table class="mtx">
      <thead><tr><th class="nmcol">ポケモン</th><th colspan="2">タイプ</th>${head}
      <th>特性</th><th>H</th><th>A</th><th>B</th><th>C</th><th>D</th><th>S</th>
      <th>物理<br>耐久</th><th>特殊<br>耐久</th></tr></thead>
      <tbody>${body}</tbody></table></div>`;
  }

  /* 自分側の行。メガストーン持ちはメガ／非メガを切り替えられる
     （どちらで見るかは相手と同じく使う人が決める）。 */
  function myMatrixRows(slots) {
    return slots.map((slot, i) => {
      const canMega = !!(slot.mega && slot.base);
      if (megaOn[slot.name] === undefined) megaOn[slot.name] = true;
      const m = slot.plain || (megaOn[slot.name] ? slot.mega : slot.base);
      if (!m) return '';
      const btn = canMega
        ? ` <button class="megatg" data-slot="${esc(slot.name)}" ` +
          `aria-pressed="${megaOn[slot.name]}">${megaOn[slot.name] ? 'メガ' : '非メガ'}</button>`
        : '';
      return matrixRow({
        dexName: m.species, ability: m.ability,
        head: `<td class="nmcol">${esc(m.name)}${btn}</td>`,
      });
    }).filter(Boolean);
  }

  /* メガ／非メガのボタンの見出し。メガリザードンのようにX・Yが両方ある種があるので、
     「メガ」で一括りにせず末尾のX/Yまで出す。 */
  function formLabel(name) {
    if (!DEX[name] || !DEX[name].mega) return '非メガ';
    const tail = name.slice(-1);
    return (tail === 'X' || tail === 'Y') ? 'メガ' + tail : 'メガ';
  }

  function oppMatrixRows(entries) {
    return entries.map(sp => {
      // 表示する形態。切り替えていなければ入力どおり（使用率データの形態）
      const shown = oppForm[sp.name] || sp.name;
      const chain = (DEX[shown] && DEX[shown].forms) || [];
      const t = sp.rows[0];
      // 使用率データの特性は、その形態のときだけ意味がある。
      // メガ／非メガを切り替えたら図鑑からの仮定に戻す
      const ability = (shown === sp.name && t) ? (t.ability_ja || t.ability) : null;
      const btn = chain.length > 1
        ? ` <button class="megatg" data-opp="${esc(sp.name)}" ` +
          `aria-pressed="${!!DEX[shown].mega}">${esc(formLabel(shown))}</button>`
        : '';
      const rk = sp.rank ? `<span class="rk">${sp.rank}位</span> ` : '';
      return matrixRow({
        dexName: shown,
        ability: (ability && DEX[shown].ab_list.includes(ability)) ? ability : null,
        head: `<td class="nmcol">${rk}${esc(shown)}${btn}</td>`,
      });
    }).filter(Boolean);
  }

  // ---------------------------------------------------------- 推奨選出

  /* 3体の組み合わせを全通り試す。貪欲法にしないのは、
     「その相手を処理できるのが1体だけ」という相手を取りこぼすため。
     枠は6つしかないので C(6,3)×メガの選び方 = せいぜい60通りしかない。 */
  function recommend(slots, targets) {
    if (!targets.length || slots.length === 0) return null;
    const pickSize = Math.min(3, slots.length);
    const combos = [];
    const walk = (start, cur) => {
      if (cur.length === pickSize) { combos.push(cur.slice()); return; }
      for (let i = start; i < slots.length; i++) { cur.push(i); walk(i + 1, cur); cur.pop(); }
    };
    walk(0, []);

    // 安定して見られる相手の数 → 条件付きも含めた数 → 通る型の総数、の順に良いものを採る。
    // 3つ目は同点のときの気休めで、器用な組み合わせのほうを選ぶための順位付け。
    const better = (a, b) => {
      for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] > b[i];
      return false;
    };

    let best = null;
    for (const combo of combos) {
      // メガシンカできるのは1体だけ。誰をメガにするかまで込みで数える
      const megaIdx = combo.filter(i => slots[i].mega);
      const choices = megaIdx.slice();
      choices.push(null);                       // 誰もメガにしない場合も一応見る
      for (const useMega of choices) {
        const forms = combo.map(i => formOf(slots[i], i === useMega));
        if (forms.some(f => !f)) continue;
        let stable = 0, partial = 0, rows = 0;
        for (const sp of targets) {
          const vs = forms.map(f => verdictFor(f, sp));
          if (vs.some(v => v.level === 2)) stable++;
          else if (vs.some(v => v.level === 1)) partial++;
          for (const f of forms) rows += sp.rows.filter(t => check(f, t).ok).length;
        }
        const score = [stable, partial, rows];
        if (!best || better(score, best.score)) best = { score, combo, useMega, forms };
      }
    }
    return best;
  }

  // ---------------------------------------------------------- 描画

  function renderSlots() {
    $('slots').innerHTML = picks.map((v, i) => `
      <div class="slot">
        <input id="in${i}" type="text" value="${esc(v)}" placeholder="${i + 1}体目"
          autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
        <div class="sug" id="sug${i}"></div>
      </div>`).join('');
    for (let i = 0; i < SLOTS; i++) bindSlot(i);
  }

  /* 入力欄そのものは作り直さない。作り直すとIMEの変換が中断される
     （パーティー登録画面で実際に踏んだ不具合と同じ）。候補欄だけ書き換える。 */
  function bindSlot(i) {
    const el = $('in' + i);
    const sug = $('sug' + i);
    const redrawSug = () => {
      const list = suggest(el.value);
      const exact = list.length === 1 && list[0].name === el.value.trim();
      if (!el.value.trim() || exact) { sug.innerHTML = ''; return; }
      sug.innerHTML = list.map(s =>
        `<button type="button" data-n="${esc(s.name)}">${esc(s.name)}<i>${s.rank}位</i></button>`
      ).join('');
    };
    el.addEventListener('input', () => { picks[i] = el.value; redrawSug(); render(); });
    el.addEventListener('focus', redrawSug);
    el.addEventListener('blur', () => setTimeout(() => { sug.innerHTML = ''; }, 150));
    el.addEventListener('keydown', ev => {
      if (ev.key !== 'Enter') return;
      const list = suggest(el.value);
      if (list.length) {
        el.value = picks[i] = list[0].name;
        sug.innerHTML = '';
        render();
        const next = $('in' + (i + 1));
        if (next) next.focus();
      }
    });
    sug.addEventListener('mousedown', ev => {
      const b = ev.target.closest('button');
      if (!b) return;
      ev.preventDefault();
      el.value = picks[i] = b.dataset.n;
      sug.innerHTML = '';
      render();
      const next = $('in' + (i + 1));
      if (next) next.focus();
    });
  }

  function typeChips(t) {
    return t.types.filter(Boolean).map(x =>
      `<span class="pat" style="--tc:${R.typeColor[x] || '#666'}">${esc(x)}</span>`).join(' ');
  }

  function renderOpponent(sp, slots) {
    // %は型ごとの値なので、同じ型の行（マルチスケイル解除など）には出さない
    const shown = new Set();
    const head = sp.rows.map(t => {
      const dup = shown.has(t.pattern);
      shown.add(t.pattern);
      return `<span class="mv${dup ? ' st' : ''}">${esc(rowKey(t))}` +
        (dup ? '' : ` <i>${t.share}%</i>`) + `</span>`;
    }).join('');
    const t0 = sp.rows[0];

    const graded = [];
    for (const slot of slots) {
      for (const useMega of [true, false]) {
        const f = formOf(slot, useMega);
        if (!f) continue;
        const v = verdictFor(f, sp);
        if (v.level) graded.push({ f, v });
        if (slot.plain) break;      // メガ形態を持たない駒は1回でよい
      }
    }
    // 超有利（★）は安定の中でも上に出す。探しているのはたいていこれ
    graded.sort((a, b) => b.v.level - a.v.level
      || (b.v.sup ? 1 : 0) - (a.v.sup ? 1 : 0) || b.v.share - a.v.share);
    const stable = graded.filter(g => g.v.level === 2);
    const partial = graded.filter(g => g.v.level === 1);

    const line = (g, withPat) =>
      `<div class="prow${g.v.sup ? ' sup' : ''}">` +
      `<span class="me">${g.v.sup ? '<span class="star">★</span>' : ''}${esc(label(g.f))}</span>` +
      `<span class="hit"><b>${esc(g.v.move)}</b></span>` +
      `<span class="alt">${esc(g.v.why)}</span>` +
      (g.v.sup ? `<span class="suptag">超有利</span>` : '') +
      (withPat ? `<span class="rare">通るのは <b>${esc(g.v.keys.join(' / '))}</b>・計${g.v.share}%</span>` : '') +
      `</div>`;

    let body = '';
    if (stable.length) {
      body += `<div class="grp"><span class="vd v1">安定</span><div>${stable.map(g => line(g, false)).join('')}</div></div>`;
    }
    if (partial.length) {
      body += `<div class="grp"><span class="vd v2">条件付き</span><div>${partial.map(g => line(g, true)).join('')}</div></div>`;
    }
    if (!graded.length) {
      // 処理できる駒が無いときこそ情報が要る。最大打点と最も痛い被弾を出す
      let bestHit = null, worst = null;
      for (const slot of slots) {
        for (const f of [slot.plain, slot.mega, slot.base]) {
          if (!f) continue;
          for (const t of sp.rows) {
            const [p] = Engine.chooseMove(f.moves.map(mv => Engine.myHit(f, mv, t)));
            if (p && (!bestHit || p.ph > bestHit.ph)) bestHit = { f, t, ...p };
            const b = Engine.theirHit(t, f);
            if (b.move !== '—' && (!worst || b.ph > worst.ph)) worst = { f, t, ...b };
          }
        }
      }
      body += `<div class="grp"><span class="vd v6">処理不可</span><div>`;
      if (bestHit) {
        body += `<div class="prow"><span class="me">${esc(label(bestHit.f))}</span>` +
          `<span class="hit"><b>${esc(bestHit.move)}</b> ${bestHit.ph}%</span>` +
          `<span class="alt">これが最大打点（${esc(bestHit.verdict)}）</span></div>`;
      }
      if (worst) {
        body += `<div class="prow"><span class="me">被弾</span>` +
          `<span class="hit"><b>${esc(worst.move)}</b> ${worst.ph}%</span>` +
          `<span class="alt">${esc(label(worst.f))} が最も痛い</span></div>`;
      }
      body += `</div></div>`;
    }

    return `<div class="card">
      <div class="chead">
        <span class="rk">${t0.rank}位</span>
        <!-- 名前は行側（t0）から出す。「セグレイブ」と入れても使用率データは
             メガセグレイブなので、種族値も特性もメガのものが並ぶ。
             入力どおりの名前を出すと、メガの数字に通常形態の名前が付いて嘘になる -->
        <span class="nm">${esc(t0.name)}</span>
        ${typeChips(t0)}
        <span class="tag">S<b>${t0.speed}</b>${t0.scarf ? '★' : ''}
          / ${esc(t0.ability_ja || t0.ability)} / ${esc(t0.item || '—')}</span>
        <span class="stats">${head}</span>
      </div>
      <div class="wkrow">${UI.weakChips(t0, R.typeColor)}</div>
      <div class="pbody">${body}</div>
    </div>`;
  }

  function renderRecommend(rec, targets, slots) {
    if (!rec) return '';
    const names = rec.forms.map(label).join(' ／ ');
    const [stable, partial] = rec.score;
    const uncovered = targets.filter(sp => !rec.forms.some(f => verdictFor(f, sp).level === 2));
    const megaSlots = rec.combo.filter(i => slots[i].mega);
    let note = '';
    if (megaSlots.length > 1) {
      const who = rec.useMega === null ? 'どれもメガにしない'
        : `${slots[rec.useMega].name} をメガにする`;
      note = `<div class="prow"><span class="me">メガ枠</span>` +
        `<span class="alt">メガストーン持ちが${megaSlots.length}体。1体しかメガれないので ${esc(who)} 前提の数字</span></div>`;
    }
    return `<div class="card">
      <div class="chead"><span class="nm">推奨選出</span>
        <span class="tag">${targets.length}体中 <b>${stable}</b>体を安定して見られる` +
      (partial ? `（条件付きを含めれば <b>${stable + partial}</b>体）` : '') + `</span></div>
      <div class="pbody">
        <div class="prow"><span class="me" style="font-size:17px">${esc(names)}</span></div>
        ${note}
        ${uncovered.length
        ? `<div class="prow"><span class="me">残る不安</span><span class="alt">` +
            `${uncovered.map(s => esc(s.name)).join(' , ')} は安定して見られる駒が居ない</span></div>`
        : `<div class="prow"><span class="alt">相手6体すべてに安定した回答がある</span></div>`}
      </div>
    </div>`;
  }

  function render() {
    const slots = buildSlots(MEMBERS);
    const seen = new Set();
    const picked = [];           // 図鑑にある相手（相性表はこれ全部で出せる）
    const ambiguous = [], missing = [];
    picks.forEach(v => {
      if (!v.trim()) return;
      const sp = resolve(v);
      if (!sp) {
        // 「候補が複数で決まらない」と「そもそも居ない」は別の話。混ぜると直しようがない
        (suggest(v).length ? ambiguous : missing).push(v.trim());
        return;
      }
      // 「セグレイブ」と「メガセグレイブ」は同じ使用率データを指すので、
      // 両方入力されても1体として扱う（借りた行の名前で重複を見る）
      const key = sp.rows.length ? sp.rows[0].name : sp.name;
      if (seen.has(key)) return;
      seen.add(key);
      picked.push(sp);
    });
    // 処理判定は使用率データ（型・技・持ち物）が要るので、圏外の相手には出せない
    const targets = picked.filter(sp => sp.rows.length);
    // 入力された6体に天気・フィールドを張る駒が居るなら、影響を受ける相手の行を割る。
    // **キャッシュも捨てる。** 同じ相手でも場の状態が変われば判定が変わる
    cache.clear();
    const splitNames = expandRows(targets, slots.flatMap(
      g => [g.plain, g.mega, g.base].filter(Boolean)));
    const noUsage = picked.filter(sp => !sp.rows.length);

    let html = '';
    if (picked.length) {
      html += `<section class="card">` +
        matrixTable([{ title: '相手', rows: oppMatrixRows(picked) },
                     { title: '自分', rows: myMatrixRows(slots) }]) +
        `<div class="wkrow"><span class="wklbl">倍率</span>` +
        `<span class="ef e4">4</span><span class="ef e2">2</span>` +
        `<span class="ef e1">1</span><span class="ef eh">0.5</span>` +
        `<span class="ef e0">0</span>` +
        `<span class="wklbl">括弧は特性で変わった値。特性欄の<b>太字</b>がその特性、<u>下線</u>は持っていれば倍率が変わる特性</span>` +
        `<span class="wklbl">種族値は無補正。物理耐久=H×B/1000・特殊耐久=H×D/1000</span>` +
        `<span class="wklbl">タイプは1文字表記（ノ炎水電草氷格毒地飛超虫岩霊竜悪鋼妖）。列に触れると正式名が出る</span>` +
        `</div></section>`;
    }

    if (splitNames.length) {
      html += `<div class="card"><div class="pbody"><div class="grp">` +
        `<span class="vd v2">場の状態</span><div><div class="prow">` +
        `<span class="me">${esc(splitNames.join(' , '))}</span>` +
        `<span class="alt">この相手は、同じパーティに居る天気・フィールドの張り手が` +
        `出ているかどうかで数字が変わる。<b>張った場合と張らない場合の両方</b>を行に分けて` +
        `あり、どちらも処理できたときだけ「安定」にしている</span>` +
        `</div></div></div></div></div>`;
    }

    if (missing.length || ambiguous.length || noUsage.length) {
      const lines = [];
      if (missing.length) {
        lines.push(`<div class="prow"><span class="me">図鑑に無い</span><span class="alt">` +
          `${missing.map(esc).join(' , ')} は図鑑に見つからない。名前を確認してほしい</span></div>`);
      }
      if (ambiguous.length) {
        lines.push(`<div class="prow"><span class="me">候補が複数</span><span class="alt">` +
          `${ambiguous.map(esc).join(' , ')} は1体に決まらない。候補から選んでほしい</span></div>`);
      }
      if (noUsage.length) {
        lines.push(`<div class="prow"><span class="me">処理判定なし</span><span class="alt">` +
          `${noUsage.map(sp => esc(sp.name)).join(' , ')} は使用率${R.threatRankLimit}位より下で、` +
          `型・技・持ち物のデータが無い。上の相性表には出しているが、` +
          `どの駒で処理できるかは計算できない</span></div>`);
      }
      html += `<div class="card"><div class="pbody"><div class="grp">` +
        `<span class="vd v6">注意</span><div>${lines.join('')}</div></div></div></div>`;
    }

    if (!picked.length) {
      $('result').innerHTML = html || `<div class="empty"><h2>相手の6体を入れてください</h2>
        <p>ひらがなのまま数文字打つと候補が出る。Enter で確定して次の欄へ進む。</p></div>`;
      $('cnt').textContent = '';
      return;
    }

    if (targets.length) {
      html += renderRecommend(recommend(slots, targets), targets, slots);
      // 見出しを兼ねた★の凡例。カードが並ぶだけだと何の一覧なのか分からない
      html += `<div class="seclbl">相手別の担当<span>` +
        `<b class="star">★</b>は超有利 — 先手を取って1発、または返しが最大乱数でも` +
        `${R.superTakePh}%以下のまま1発。相手の全部の型に対して成り立つときだけ付く</span></div>`;
      html += targets.map(sp => renderOpponent(sp, slots)).join('');
    }
    $('result').innerHTML = html;
    $('cnt').textContent = `相手 ${picked.length}体（処理判定 ${targets.length}体）`
      + ` / 自分 ${slots.length}枠`;

    // メガ切替。相性表だけ作り直せばよいので、入力欄には触らない
    $('result').querySelectorAll('.megatg').forEach(b => {
      b.addEventListener('click', () => {
        if (b.dataset.slot) {
          megaOn[b.dataset.slot] = !megaOn[b.dataset.slot];
        } else {
          // 相手側。X・Yがある種は3状態あるので、順に送る
          const key = b.dataset.opp;
          const shown = oppForm[key] || key;
          const chain = (DEX[shown] && DEX[shown].forms) || [];
          if (chain.length > 1) {
            oppForm[key] = chain[(chain.indexOf(shown) + 1) % chain.length];
          }
        }
        render();
      });
    });
  }

  function showParty(members, source, warning) {
    const names = members.filter(m => m.form !== '非メガ').map(label).join('・');
    $('pstat').innerHTML =
      (warning ? `<span class="warn">${esc(warning)}</span> ` : '') +
      `<span>${esc(source)}</span><b>${esc(names)}</b>` +
      `<a class="navlink" href="party.html">変更</a>`;
  }

  function showEmpty(message) {
    $('result').innerHTML =
      `<div class="empty"><h2>パーティーが読み込めません</h2><p>${esc(message)}</p>` +
      `<a class="navlink primary" href="party.html">パーティー登録画面をひらく</a></div>`;
  }

  // ---------------------------------------------------------- 起動

  async function main() {
    const loaded = {};
    for (const n of ['dex', 'moves', 'types', 'rules', 'threats']) {
      const res = await fetch(`appdata/${n}.json`);
      if (!res.ok) throw new Error(`appdata/${n}.json が読めません`);
      loaded[n] = await res.json();
    }
    Engine.load(loaded);
    R = loaded.rules;
    THREATS = loaded.threats;

    DEX = loaded.dex;

    // 同じポケモンの型違いは1つにまとめる。相手の型は対戦前に分からないので、
    // 入力は名前だけで受けて、型の違いは判定側で「安定／条件付き」に落とす
    /* eslint-disable no-inner-declarations */
    function borrowForm(name, byName) {
      // dex.json の forms は同じ図鑑番号のメガ切替の並び（通常→メガ→Zメガ）。
      // 自分以外の形態が使用率データに居るなら、その行をそのまま使う。
      for (const other of (DEX[name] && DEX[name].forms) || []) {
        if (other !== name && byName.has(other)) {
          const g = byName.get(other);
          return { name, rank: g.rank, rows: g.rows };
        }
      }
      return null;
    }
    const byName = new Map();
    for (const t of THREATS) {
      const g = byName.get(t.name) || { name: t.name, rank: t.rank, rows: [] };
      g.rows.push(t);
      byName.set(t.name, g);
    }
    // **候補は図鑑の全ポケモン。** 相性表と種族値は使用率データが無くても出せる。
    // 使用率圏外の相手は rows が空になり、処理判定だけ出せない扱いになる。
    // 並びは使用率順→図鑑順。実戦で入れるのはほとんど上位なので、そちらを先に出す。
    //
    // メガ率が高いポケモンは、使用率データ側に**メガ形態の名前でしか出てこない**
    // （セグレイブ8位は「メガセグレイブ」として入っている）。通常形態の名前で引いたときに
    // 「圏外なのでデータが無い」と出すのは嘘なので、同じ図鑑番号の形態から借りる。
    SPECIES = Object.keys(DEX).map(name => byName.get(name)
      || borrowForm(name, byName) || { name, rank: null, rows: [] });
    SPECIES.sort((a, b) => (a.rank || 9999) - (b.rank || 9999));
    // 照合用のキーはここで1回だけ作る。1文字打つたびに313体ぶん作り直さない
    for (const s of SPECIES) { s.k = fold(s.name); s.ks = strip(s.name); }

    let text = PartyStore.load();
    let source = '登録済みのパーティで計算';
    let warning = '';
    if (!text) {
      const res = await fetch('party.txt');
      if (!res.ok) { showEmpty('party.txt が読み込めませんでした。'); return; }
      text = await res.text();
      source = '既定の party.txt で計算（未登録）';
    }
    try {
      MEMBERS = Engine.parseParty(text);
    } catch (e) {
      const res = await fetch('party.txt');
      if (!res.ok) { showEmpty(e.message); return; }
      try {
        MEMBERS = Engine.parseParty(await res.text());
        source = '既定の party.txt で計算';
        warning = '登録したパーティに問題があるため既定を使用中:';
      } catch (e2) { showEmpty(e.message); return; }
    }

    showParty(MEMBERS, source, warning);
    renderSlots();
    render();
    $('clear').addEventListener('click', () => {
      picks = new Array(SLOTS).fill('');
      renderSlots();
      render();
      $('in0').focus();
    });
    $('in0').focus();
  }

  main().catch(e => showEmpty(e.message));
})();
