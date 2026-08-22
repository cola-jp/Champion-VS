/* 対面ダメージ表。登録されたパーティで上位ポケモンへの打点と被弾を出す。
 *
 * 表示の決まりは build/generate.py の render_card / render_row からの移植。
 * ステルスロックの切り替えは、以前は両方の行を書き出して CSS で見せ分けていたが、
 * これは JS なしで読める必要があったための作りだった。JS 前提になったので
 * 切り替え時に計算し直す（行数が半分で済む）。
 */
'use strict';

(() => {
  const $ = id => document.getElementById(id);
  let THREATS = [], MEMBERS = [], R = null;
  let showNonMega = true, srOn = false;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* 倍率の表記。Python 側は float なので 1.0 / 2.0 と出る。JSONを読むと 1 / 2 に
     なってしまうので、整数値のときだけ小数第1位まで書いて見た目を揃える。 */
  function mult(v) {
    return Number.isInteger(v) ? v.toFixed(1) : String(v);
  }

  function bar(pl, ph, color) {
    const a = Math.min(pl, 100), b = Math.min(ph, 100);
    return `<div class="trk"><div class="half"></div>` +
      `<div class="fill hi" style="width:${b}%;background:${color}"></div>` +
      `<div class="fill" style="width:${a}%;background:${color}"></div></div>`;
  }

  // ---------------------------------------------------------- 1行

  function renderRow(member, threat, hpEff) {
    const hits = member.moves.map(mv => Engine.myHit(member, mv, threat, hpEff));
    const [primary, alt] = Engine.chooseMove(hits);
    if (!primary) return '';

    const vclass = R.verdictClass[primary.verdict] || 'v5';
    const vcolor = R.verdictColor[primary.verdict] || 'var(--weak)';
    const back = Engine.theirHit(threat, member);
    const danger = back.ph >= 100 ? ' dg' : '';
    const faster = member.speed > threat.speed;
    const drawback = new Set(R.drawbackMoves);

    let tags = '';
    if (primary.hits) tags += ` <span class="hits">${esc(primary.hits)}</span>`;
    if (primary.disguise) tags += ' <span class="abm">ばけのかわ+1発</span>';
    if (primary.ab_name) tags += ` <span class="abm">${esc(primary.ab_name)}×${mult(primary.ab_mult)}</span>`;
    if (drawback.has(primary.move)) tags += ' <span class="rl">反動</span>';
    if (primary.acc) tags += ` <span class="ac">命中${Engine.pyRound(primary.acc)}%</span>`;
    const ohko = hits.find(h => h && h.ohko);
    if (ohko) tags += ` <span class="ohko">＋${esc(ohko.move)} ${Engine.pyRound(ohko.acc)}%</span>`;

    let sub = '';
    if (alt) {
      let atags = '';
      if (alt.ab_name) atags += ` <span class="abm">${esc(alt.ab_name)}×${mult(alt.ab_mult)}</span>`;
      if (drawback.has(alt.move)) atags += ' <span class="rl">反動</span>';
      if (alt.acc) atags += ` <span class="ac">命中${Engine.pyRound(alt.acc)}%</span>`;
      const up = (R.verdictRank[alt.verdict] || 0) > (R.verdictRank[primary.verdict] || 0);
      sub += `<div class="${up ? 'alt up' : 'alt'}">${esc(alt.move)}${atags}: ` +
             `${alt.pl}-${alt.ph}% ${alt.verdict}</div>`;
    }
    const boosted = Engine.boostedHit(member, threat, hpEff);
    if (boosted) {
      sub += `<div class="d1">${esc(member.boosting_move)}+${boosted.stages}: ${esc(boosted.move)} ` +
             `${boosted.pl}-${boosted.ph}% ${boosted.verdict}</div>`;
    }

    // 被弾側の注記。連続技の回数、皮で1回止まること、条件付き特性が剥がれたときの数字。
    let backTags = '';
    if (back.hits) backTags += ` <span class="hits">${esc(back.hits)}</span>`;
    if (back.disguise) backTags += ' <span class="abm">皮が剥がれた後</span>';

    let backSub = '';
    if (back.stripped) {
      const cls = back.stripped.ph >= 100 ? 'rare hot' : 'rare';
      backSub += `<div class="${cls}">${esc(back.stripped_label)} ` +
                 `<b>${esc(back.stripped.move)}</b> ${back.stripped.ph}%</div>`;
    }
    if (back.rare) {
      const cls = back.rare.ph >= 100 ? 'rare hot' : 'rare';
      backSub += `<div class="${cls}">低採用 <b>${esc(back.rare.move)}</b>` +
                 `（${Engine.pyRound(back.rare.usage)}%） ${back.rare.ph}%</div>`;
    }

    const formLabel = member.form ? `<small>${esc(member.form)}</small>` : '';
    const cls = member.form === '非メガ' ? 'nonmega' : '';
    return `<tr class="${cls}">` +
      `<td class="me">${esc(member.name)}${formLabel}` +
      `<span class="spd ${faster ? 'up' : 'dn'}">${faster ? '先手' : '後手'}</span></td>` +
      `<td class="hit"><b>${esc(primary.move)}</b> ` +
      (primary.nullified ? '<span class="nul">通らない</span> '
                         : `${primary.lo}-${primary.hi} `) +
      `<span class="mul">×${mult(primary.eff)}</span>${tags}${sub}</td>` +
      `<td class="barcell">${bar(primary.pl, primary.ph, vcolor)}</td>` +
      `<td class="vdcell"><span class="vd ${vclass}">` +
      `${primary.nullified ? '無効' : primary.verdict}</span></td>` +
      `<td class="pct">${primary.nullified ? '—' : `${primary.pl}-${primary.ph}%`}</td>` +
      `<td class="back${danger}">被弾 <b>${esc(back.move)}</b>${backTags} ${back.ph}%${backSub}</td></tr>`;
  }

  // ---------------------------------------------------------- 1カード

  /* タイプの色。複合タイプは2色目も返す（帯を上下で塗り分けるため）。
     単タイプは --tc2 を出さず、CSS 側で --tc に落ちるようにしている。 */
  function typeVars(types) {
    const c1 = R.typeColor[types[0]] || '#666';
    const c2 = types[1] ? (R.typeColor[types[1]] || '#666') : null;
    return `--tc:${c1}` + (c2 ? `;--tc2:${c2}` : '');
  }

  function renderCard(threat, id) {
    const typeLabel = threat.types[0] + (threat.types[1] ? '/' + threat.types[1] : '');
    const sr = Engine.srDamage(threat);
    const hpEff = srOn && sr ? Math.max(threat.st[0] - sr, 1) : undefined;

    let chips = '';
    if (sr && srOn) chips += `<span class="pat sr-chip-on">SR -${sr}</span>`;
    if (threat.multi) chips += `<span class="pat">${esc(threat.pattern)} ${threat.share}%</span>`;
    if (threat.form) chips += `<span class="pat alt">${esc(threat.form)}</span>`;
    if (threat.hp_full === true) chips += '<span class="pat alt">マルチスケイル有効</span>';
    if (threat.hp_full === false) chips += '<span class="pat ms-off">マルチスケイル解除</span>';
    if (threat.protean === true) chips += '<span class="pat alt">へんげんじざい発動</span>';
    if (threat.protean === false) chips += '<span class="pat ms-off">へんげんじざい未発動</span>';

    let moveChips = '';
    for (const mv of threat.moves.slice(0, 8)) {
      const m = Engine.moves[mv.name];
      const isAtk = m && m.power;
      const extra = R.multiHit[mv.name] ? ' ' + R.multiHit[mv.name] : '';
      const label = isAtk ? `<b>${esc(mv.name)}</b>` : esc(mv.name);
      moveChips += `<span class="mv${isAtk ? '' : ' st'}">${label} ` +
                   `<i>${mv.usage.toFixed(1)}%${esc(extra)}</i></span>`;
    }

    const rows = MEMBERS.map(m => renderRow(m, threat, hpEff)).join('');
    const st = threat.st;
    const abJa = threat.ability_ja || threat.ability;
    const off = threat.hp_full === false ? ' class=off' : '';

    return `<section class="card" id="${id}" data-n="${esc(threat.name)}" style="${typeVars(threat.types)}">` +
      `<div class="chead"><span class="rk">#${threat.rank}</span>` +
      `<span class="nm">${esc(threat.name)}</span>${chips}` +
      `<span class="tag">${esc(typeLabel)}・<b${off}>${esc(abJa)}</b>・` +
      `${esc(threat.item)}・${esc(threat.nature)}</span>` +
      `<span class="stats">H<b>${st[0]}</b> A<b>${st[1]}</b> B<b>${st[2]}</b> C<b>${st[3]}</b> ` +
      `D<b>${st[4]}</b> S<b>${threat.speed}</b>${threat.scarf ? '★' : ''}</span>` +
      `<a class="top" href="#idx">↑</a></div>` +
      `<div class="mvrow">${moveChips}</div>` +
      `<table><thead><tr><th>味方</th><th>最大打点</th><th>ダメージ</th>` +
      `<th>判定</th><th>%</th><th>被弾</th></tr></thead><tbody>${rows}</tbody></table></section>`;
  }

  // ---------------------------------------------------------- 全体

  function renderAll() {
    const links = [], cards = [];
    THREATS.forEach((t, i) => {
      const id = 'p' + i;
      let label = t.name;
      if (t.multi) label += ' ' + t.pattern;
      if (t.form) label += ' ' + t.form;
      if (t.hp_full === true) label += ' MS有効';
      if (t.hp_full === false) label += ' MS解除';
      if (t.protean === true) label += ' 変幻発動';
      if (t.protean === false) label += ' 変幻未発動';
      links.push(`<a href="#${id}" style="${typeVars(t.types)}">${esc(label)}</a>`);
      cards.push(renderCard(t, id));
    });
    $('idx').innerHTML = `<span class="lbl">目次 — タップで移動（${links.length}件）</span>` + links.join('');
    $('cards').innerHTML = cards.join('');
    applyNonMega();
    applyFilter();
  }

  function applyNonMega() {
    document.querySelectorAll('tr.nonmega').forEach(r => r.classList.toggle('hide', !showNonMega));
  }

  function norm(s) {
    return s.replace(/[ぁ-ゖ]/g, c => String.fromCharCode(c.charCodeAt(0) + 96))
            .replace(/[ー・\s]/g, '');
  }

  function applyFilter() {
    const k = norm($('q').value.trim());
    const cards = document.querySelectorAll('.card');
    let n = 0;
    cards.forEach(c => {
      const hit = !k || norm(c.dataset.n).indexOf(k) >= 0;
      c.classList.toggle('hide', !hit);
      if (hit) n++;
    });
    $('cnt').textContent = `${n} / ${cards.length}`;
    $('idx').style.display = k ? 'none' : '';
    if (k) scrollTo(0, 0);
  }

  // ---------------------------------------------------------- パーティ状態

  function showParty(members, source, warning) {
    const st = $('pstat');
    const names = [];
    const seen = new Set();
    members.forEach(m => {
      if (seen.has(m.name)) return;
      seen.add(m.name);
      names.push(m.name);
    });
    st.className = warning ? 'pstat warn' : 'pstat';
    st.innerHTML =
      (warning ? `<b>${esc(warning)}</b> ` : '') +
      `<span>${esc(source)}</span>` +
      names.map(n => `<span class="who">${esc(n)}</span>`).join('') +
      `<a class="navlink" style="margin-left:auto" href="party.html">パーティーを編集</a>`;
  }

  function showEmpty(message) {
    $('pstat').hidden = true;
    $('idx').hidden = true;
    $('cards').innerHTML =
      `<div class="empty"><h2>パーティーが読み込めません</h2>` +
      `<p>${esc(message)}</p>` +
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

    // 登録済みのパーティを優先し、無ければリポジトリの party.txt を使う
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
      // 登録済みが壊れている場合は既定に落として、表を出しつつ警告する
      const res = await fetch('party.txt');
      if (!res.ok) { showEmpty(e.message); return; }
      try {
        MEMBERS = Engine.parseParty(await res.text());
        source = '既定の party.txt で計算';
        warning = '登録したパーティに問題があるため既定を使用中:';
      } catch (e2) { showEmpty(e.message); return; }
    }

    showParty(MEMBERS, source, warning);
    renderAll();

    $('q').addEventListener('input', applyFilter);
    $('tM').addEventListener('click', ev => {
      showNonMega = !showNonMega;
      ev.currentTarget.setAttribute('aria-pressed', showNonMega);
      applyNonMega();
    });
    $('tS').addEventListener('click', ev => {
      srOn = !srOn;
      ev.currentTarget.setAttribute('aria-pressed', srOn);
      renderAll();
    });
    addEventListener('keydown', ev => {
      if (ev.key === '/' && document.activeElement !== $('q')) {
        ev.preventDefault(); $('q').focus(); $('q').select();
      }
      if (ev.key === 'Escape') { $('q').value = ''; applyFilter(); }
    });
    $('tools').hidden = false;
  }

  main().catch(e => showEmpty(e.message));
})();
