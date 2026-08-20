/* パーティー登録画面。
 * 取り込み（party.txt 形式）→ 画面上で調整 → 保存／書き出し。
 *
 * 検証は Engine.parseParty をそのまま使う。画面用に別のチェックを書くと、
 * 画面では通るのに計算側で落ちる（またはその逆）という食い違いが必ず出る。
 */
'use strict';

(() => {
  const STAT_LABELS = ['H', 'A', 'B', 'C', 'D', 'S'];
  const EMPTY = () => ({ name: '', item: '', natureJa: '', ability: '', stats: ['', '', '', '', '', ''], moves: ['', '', '', ''] });

  let entries = [];
  const $ = id => document.getElementById(id);

  // ---------------------------------------------------------- テキスト↔データ

  function entryToBlock(e) {
    return [
      `${e.name} @ ${e.item}`,
      `${e.natureJa} / ${e.ability}`,
      e.stats.join('-'),
      e.moves.filter(m => m.trim()).join(' / '),
    ].join('\n');
  }

  function entriesToText(list) {
    return list.map(entryToBlock).join('\n\n') + '\n';
  }

  /* 取り込み用。多少崩れていても拾えるところまで拾い、あとは画面で直してもらう。 */
  function textToEntries(text) {
    const blocks = [];
    let cur = [];
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (line.startsWith('#')) continue;
      if (!line) { if (cur.length) { blocks.push(cur); cur = []; } continue; }
      cur.push(line);
    }
    if (cur.length) blocks.push(cur);

    return blocks.map(lines => {
      const e = EMPTY();
      const [l1 = '', l2 = '', l3 = '', l4 = ''] = lines;
      if (l1.includes('@')) {
        const i = l1.indexOf('@');
        e.name = l1.slice(0, i).trim();
        e.item = l1.slice(i + 1).trim();
      } else { e.name = l1.trim(); }
      if (l2.includes('/')) {
        const i = l2.indexOf('/');
        e.natureJa = l2.slice(0, i).trim();
        e.ability = l2.slice(i + 1).trim();
      } else { e.natureJa = l2.trim(); }
      const parts = l3.split('-').map(s => s.trim());
      for (let i = 0; i < 6; i++) e.stats[i] = parts[i] || '';
      const mv = l4.split('/').map(s => s.trim()).filter(Boolean);
      for (let i = 0; i < 4; i++) e.moves[i] = mv[i] || '';
      return e;
    });
  }

  // ---------------------------------------------------------- 検証

  /* 1体だけを Engine.parseParty に通す。他の体が壊れていても、この体の
     能力ポイントとエラーは出せるようにするため1体ずつ呼ぶ。 */
  function validateEntry(e) {
    try {
      const members = Engine.parseParty(entryToBlock(e));
      return { ok: true, ev: members[0].ev, members };
    } catch (err) {
      if (err instanceof Engine.PartyError) return { ok: false, error: err.message };
      return { ok: false, error: String(err && err.message || err) };
    }
  }

  function validateAll() {
    const results = entries.map(validateEntry);
    const okCount = results.filter(r => r.ok).length;
    return { results, okCount, allOk: entries.length > 0 && okCount === entries.length };
  }

  // ---------------------------------------------------------- 描画

  function typeColorOf(name) {
    const d = Engine.dex[name];
    if (!d) return '#666';
    return Engine.rules.typeColor[d.t1] || '#666';
  }

  function render() {
    const { results, allOk } = validateAll();
    const list = $('list');
    list.innerHTML = '';

    entries.forEach((e, i) => {
      const r = results[i];
      const dex = Engine.dex[e.name];
      const card = document.createElement('section');
      card.className = 'mon' + (r.ok ? '' : ' bad');
      card.style.setProperty('--tc', typeColorOf(e.name));

      const typeLabel = dex ? dex.t1 + (dex.t2 ? '/' + dex.t2 : '') : '—';
      const evLine = r.ok
        ? `<div class="evline">${STAT_LABELS.map((l, k) => `<span>${l}<b>${r.ev[k]}</b></span>`).join('')}
           <span>合計<b class="${r.ev.reduce((a, b) => a + b, 0) > Engine.rules.maxPointsTotal ? 'over' : ''}">${r.ev.reduce((a, b) => a + b, 0)}</b>/${Engine.rules.maxPointsTotal}</span>
           ${r.members.length > 1 ? '<span>メガ／非メガの2件を生成</span>' : ''}</div>`
        : '';

      card.innerHTML = `
        <div class="mhead">
          <span class="idx">#${i + 1}</span>
          <span class="mname">${esc(e.name) || '（未入力）'}</span>
          <span class="mtype">${esc(typeLabel)}</span>
          <span class="sp">
            <button class="act mini" data-act="up" data-i="${i}" ${i === 0 ? 'disabled' : ''}>↑</button>
            <button class="act mini" data-act="down" data-i="${i}" ${i === entries.length - 1 ? 'disabled' : ''}>↓</button>
            <button class="act mini" data-act="del" data-i="${i}">削除</button>
          </span>
        </div>
        <div class="mbody">
          <div class="f"><label>ポケモン</label>
            <input data-i="${i}" data-k="name" list="dl-pokemon" value="${esc(e.name)}" placeholder="ギャラドス"></div>
          <div class="f"><label>持ち物</label>
            <input data-i="${i}" data-k="item" value="${esc(e.item)}" placeholder="ギャラドスナイト"></div>
          <div class="f"><label>性格</label>
            <input data-i="${i}" data-k="natureJa" list="dl-nature" value="${esc(e.natureJa)}" placeholder="ようき"></div>
          <div class="f"><label>特性</label>
            <input data-i="${i}" data-k="ability" value="${esc(e.ability)}" placeholder="いかく"
              ${dex ? `title="この種の特性: ${esc(dex.ab || '')}"` : ''}></div>
          <div class="sixin">
            ${STAT_LABELS.map((l, k) => `<div><label>${l}</label>
              <input data-i="${i}" data-k="stat${k}" inputmode="numeric" value="${esc(e.stats[k])}"></div>`).join('')}
          </div>
          <div class="movein">
            ${[0, 1, 2, 3].map(k => `<input data-i="${i}" data-k="move${k}" list="dl-moves"
              value="${esc(e.moves[k])}" placeholder="技${k + 1}">`).join('')}
          </div>
          ${evLine}
        </div>
        ${r.ok ? '' : `<div class="monerr">${esc(r.error)}</div>`}`;
      list.appendChild(card);
    });

    $('preview').textContent = entriesToText(entries);
    $('count').textContent = `${entries.length} 体`;
    $('save').disabled = !allOk;
    $('download').disabled = !allOk;

    const st = $('status');
    if (!entries.length) {
      st.className = 'pstat warn';
      st.innerHTML = 'パーティが空です。左の取り込み欄に貼り付けるか、「1体追加」から作ってください。';
    } else if (allOk) {
      const total = results.reduce((a, r) => a + r.members.length, 0);
      st.className = 'pstat';
      st.innerHTML = `<b>${entries.length}体</b>すべて有効です（ダメージ表では ${total} 行として扱われます）。`;
    } else {
      const bad = results.map((r, i) => r.ok ? null : (entries[i].name || `#${i + 1}`)).filter(Boolean);
      st.className = 'pstat warn';
      st.innerHTML = `入力に問題があります: <b>${esc(bad.join('、'))}</b> — 保存するには全て解消してください。`;
    }
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---------------------------------------------------------- 入力の受け取り

  function onInput(ev) {
    const el = ev.target;
    const i = el.dataset.i, k = el.dataset.k;
    if (i === undefined || !k) return;
    const e = entries[+i];
    if (!e) return;
    if (k.startsWith('stat')) e.stats[+k.slice(4)] = el.value.trim();
    else if (k.startsWith('move')) e.moves[+k.slice(4)] = el.value.trim();
    else e[k] = el.value.trim();
    scheduleRender(el);
  }

  /* 入力のたびに全部描き直すとフォーカスが飛ぶので、少し待ってから描き直し、
     描き直した後で同じ入力欄にフォーカスとカーソル位置を戻す。 */
  let timer = null;
  function scheduleRender(el) {
    clearTimeout(timer);
    const key = el ? `${el.dataset.i}:${el.dataset.k}` : null;
    const pos = el && el.selectionStart;
    timer = setTimeout(() => {
      render();
      if (!key) return;
      const [i, k] = key.split(':');
      const next = document.querySelector(`[data-i="${i}"][data-k="${k}"]`);
      if (next) {
        next.focus();
        if (pos != null && next.setSelectionRange) {
          try { next.setSelectionRange(pos, pos); } catch (err) { /* number入力等 */ }
        }
      }
    }, 220);
  }

  function onClick(ev) {
    const b = ev.target.closest('button[data-act]');
    if (!b) return;
    const i = +b.dataset.i;
    if (b.dataset.act === 'del') entries.splice(i, 1);
    if (b.dataset.act === 'up' && i > 0) entries.splice(i - 1, 0, entries.splice(i, 1)[0]);
    if (b.dataset.act === 'down' && i < entries.length - 1) entries.splice(i + 1, 0, entries.splice(i, 1)[0]);
    render();
  }

  // ---------------------------------------------------------- 起動

  function fillDatalists() {
    const put = (id, items) => {
      $(id).innerHTML = items.map(v => `<option value="${esc(v)}">`).join('');
    };
    put('dl-pokemon', Object.keys(Engine.dex).sort());
    put('dl-moves', Object.keys(Engine.moves).sort());
    put('dl-nature', Object.values(Engine.rules.natureJa));
  }

  async function main() {
    const names = ['dex', 'moves', 'types', 'rules'];
    const loaded = {};
    for (const n of names) {
      const res = await fetch(`appdata/${n}.json`);
      if (!res.ok) throw new Error(`appdata/${n}.json が読めません`);
      loaded[n] = await res.json();
    }
    Engine.load(loaded);
    fillDatalists();

    const saved = PartyStore.load();
    if (saved) {
      entries = textToEntries(saved);
      $('src').value = saved;
    } else {
      const res = await fetch('party.txt');
      const text = res.ok ? await res.text() : '';
      entries = textToEntries(text);
      $('src').value = text;
    }
    render();

    $('list').addEventListener('input', onInput);
    $('list').addEventListener('click', onClick);

    $('apply').addEventListener('click', () => {
      entries = textToEntries($('src').value);
      render();
      flash('取り込みました。内容を確認して保存してください。');
    });

    $('file').addEventListener('change', async (ev) => {
      const f = ev.target.files && ev.target.files[0];
      if (!f) return;
      const text = await f.text();
      $('src').value = text;
      entries = textToEntries(text);
      render();
      flash(`${f.name} を読み込みました。`);
      ev.target.value = '';
    });

    $('add').addEventListener('click', () => { entries.push(EMPTY()); render(); });

    $('save').addEventListener('click', () => {
      const text = entriesToText(entries);
      if (PartyStore.save(text)) {
        $('src').value = text;
        flash('保存しました。ダメージ表がこのパーティで計算されます。');
      } else {
        flash('保存できませんでした（ブラウザの設定で localStorage が使えない可能性があります）。', true);
      }
    });

    $('download').addEventListener('click', () => {
      PartyStore.download(entriesToText(entries), 'party.txt');
    });

    $('reset').addEventListener('click', async () => {
      const res = await fetch('party.txt');
      const text = res.ok ? await res.text() : '';
      $('src').value = text;
      entries = textToEntries(text);
      render();
      flash('リポジトリの party.txt を読み直しました（保存はまだされていません）。');
    });
  }

  let flashTimer = null;
  function flash(msg, bad) {
    const el = $('flash');
    el.className = bad ? 'err' : 'okmsg';
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { el.hidden = true; }, 4000);
  }

  main().catch(e => {
    const el = $('flash');
    el.className = 'err';
    el.textContent = '読み込みに失敗しました: ' + e.message;
    el.hidden = false;
  });
})();
