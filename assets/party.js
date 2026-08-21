/* パーティー登録画面。
 * 取り込み（party.txt 形式）→ 画面上で調整 → 保存／書き出し。
 *
 * 努力値は「各ステータスに何ポイント振ったか」で入力する。実数値はその場で計算して
 * 併記するので、ゲーム内のステータス画面と突き合わせて確認できる。
 * party.txt に書き出すときは実数値に直す（ファイル形式は従来のまま）。
 *
 * 入力のたびにカードを作り直さないこと。作り直すと入力欄が別物に差し替わり、
 * IMEの変換中だと変換が中断されて漢字やカタカナに変換できなくなる（実際にそうなっていた）。
 * 構造が変わるとき（読み込み・追加・削除・並べ替え）だけ組み立て直し、
 * 入力中は派生表示（実数値・合計・エラー・見出し）だけを書き換える。
 */
'use strict';

(() => {
  const STAT_LABELS = ['H', 'A', 'B', 'C', 'D', 'S'];
  const EMPTY = () => ({
    name: '', item: '', natureJa: '', ability: '',
    points: ['0', '0', '0', '0', '0', '0'], moves: ['', '', '', ''],
  });

  let entries = [];
  const $ = id => document.getElementById(id);

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const natureJaToEn = ja => {
    for (const [en, name] of Object.entries(Engine.rules.natureJa)) if (name === ja) return en;
    return null;
  };

  // ---------------------------------------------------------- 実数値とポイント

  const pointsOf = e => e.points.map(p => {
    const n = parseInt(p, 10);
    return Number.isFinite(n) ? n : 0;
  });

  /* 入力されたポイントから実数値を出す。名前か性格が未確定なら null。 */
  function statsOf(e) {
    const dex = Engine.dex[e.name];
    const natureEn = natureJaToEn(e.natureJa);
    if (!dex || !natureEn) return null;
    return Engine.stats(dex.base, pointsOf(e), natureEn);
  }

  function entryToBlock(e) {
    const st = statsOf(e);
    return [
      `${e.name} @ ${e.item}`,
      `${e.natureJa} / ${e.ability}`,
      (st || pointsOf(e)).join('-'),
      e.moves.filter(m => m.trim()).join(' / '),
    ].join('\n');
  }

  const entriesToText = list => list.map(entryToBlock).join('\n\n') + '\n';

  /* party.txt を読み込む。実数値で書かれているのでポイントに逆算する。
     逆算できない値（そのポケモンでは到達しない実数値）はポイントを空にして、
     何が問題かをエラーで出す。 */
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

      const nums = l3.split('-').map(s => s.trim());
      const natureEn = natureJaToEn(e.natureJa);
      if (nums.length === 6 && nums.every(n => /^\d+$/.test(n)) && Engine.dex[e.name] && natureEn) {
        try {
          e.points = Engine.pointsFromStats(e.name, natureEn, nums.map(Number)).map(String);
        } catch (err) {
          e.importError = err.message;
        }
      } else if (l3) {
        e.importError = `実数値の行が読めません: ${l3}`;
      }

      const mv = l4.split('/').map(s => s.trim()).filter(Boolean);
      for (let i = 0; i < 4; i++) e.moves[i] = mv[i] || '';
      return e;
    });
  }

  // ---------------------------------------------------------- 検証

  /* 1体だけ検証する。他の体が壊れていてもこの体の状態は出せるように1体ずつ呼ぶ。
     ポイントの範囲だけ先に見て、残りは Engine.parseParty に任せる
     （画面用に別のチェックを書くと計算側と食い違うため）。 */
  function validateEntry(e) {
    if (e.importError) return { ok: false, error: e.importError };
    if (!e.name) return { ok: false, error: 'ポケモン名を入れてください。' };
    if (!Engine.dex[e.name]) return { ok: false, error: `ポケモン名「${e.name}」が図鑑に見つかりません。` };
    if (!e.natureJa) return { ok: false, error: '性格を入れてください。' };
    if (!natureJaToEn(e.natureJa)) return { ok: false, error: `性格「${e.natureJa}」が分かりません。` };

    const max = Engine.rules.maxPointsPerStat;
    for (let i = 0; i < 6; i++) {
      if (!/^\d+$/.test(String(e.points[i]).trim())) {
        return { ok: false, error: `${STAT_LABELS[i]}のポイントは0〜${max}の数字で入れてください。` };
      }
      if (pointsOf(e)[i] > max) {
        return { ok: false, error: `${STAT_LABELS[i]}のポイントが${pointsOf(e)[i]}です。1ステータスの上限は${max}です。` };
      }
    }
    try {
      const members = Engine.parseParty(entryToBlock(e));
      return { ok: true, ev: members[0].ev, members };
    } catch (err) {
      return { ok: false, error: String(err && err.message || err) };
    }
  }

  // ---------------------------------------------------------- 組み立て（構造）

  function setTypeColors(el, name) {
    const d = Engine.dex[name];
    const color = t => (t && Engine.rules.typeColor[t]) || '#666';
    el.style.setProperty('--tc', d ? color(d.t1) : '#666');
    if (d && d.t2) el.style.setProperty('--tc2', color(d.t2));
    else el.style.removeProperty('--tc2');
  }

  const max = () => Engine.rules.maxPointsPerStat;

  function cardHtml(e, i) {
    return `
      <div class="mhead">
        <span class="idx">#${i + 1}</span>
        <span class="mname" data-role="name"></span>
        <span class="mtype" data-role="type"></span>
        <span class="sp">
          <button class="act mini" data-act="up" data-i="${i}">↑</button>
          <button class="act mini" data-act="down" data-i="${i}">↓</button>
          <button class="act mini" data-act="del" data-i="${i}">削除</button>
        </span>
      </div>
      <div class="mbody">
        <div class="f"><label>ポケモン</label>
          <input data-i="${i}" data-k="name" list="dl-pokemon" value="${esc(e.name)}" placeholder="ギャラドス"></div>
        <div class="f"><label>持ち物</label>
          <input data-i="${i}" data-k="item" list="dl-items" value="${esc(e.item)}" placeholder="ギャラドスナイト"></div>
        <div class="f"><label>性格</label>
          <input data-i="${i}" data-k="natureJa" list="dl-nature" value="${esc(e.natureJa)}" placeholder="ようき"></div>
        <div class="f"><label>特性</label>
          <input data-i="${i}" data-k="ability" list="dl-abilities" value="${esc(e.ability)}" placeholder="いかく"></div>
        <div class="pts">
          ${STAT_LABELS.map((l, k) => `<div>
            <label>${l}</label>
            <input data-i="${i}" data-k="pt${k}" inputmode="numeric" value="${esc(e.points[k])}">
            <span class="real" data-role="stat${k}">—</span>
          </div>`).join('')}
        </div>
        <div class="movein">
          ${[0, 1, 2, 3].map(k => `<input data-i="${i}" data-k="move${k}" list="dl-moves"
            value="${esc(e.moves[k])}" placeholder="技${k + 1}">`).join('')}
        </div>
        <div class="evline">
          <span>振ったポイント <b data-role="total">0</b> / ${Engine.rules.maxPointsTotal}</span>
          <span data-role="note"></span>
        </div>
      </div>
      <div class="monerr" data-role="err" hidden></div>`;
  }

  /* カードを組み立て直す。入力欄が差し替わるので、構造が変わるときだけ呼ぶこと。 */
  function renderList() {
    const list = $('list');
    list.innerHTML = '';
    entries.forEach((e, i) => {
      const card = document.createElement('section');
      card.className = 'mon';
      card.dataset.i = String(i);
      card.innerHTML = cardHtml(e, i);
      list.appendChild(card);
    });
    refresh();
  }

  // ---------------------------------------------------------- 派生表示だけ更新

  /* 入力欄には触らない。触ると IME の変換が飛ぶ。 */
  function refresh() {
    const results = entries.map(validateEntry);
    const cards = $('list').children;

    entries.forEach((e, i) => {
      const card = cards[i];
      if (!card) return;
      const r = results[i];
      const dex = Engine.dex[e.name];
      const st = statsOf(e);
      const total = pointsOf(e).reduce((a, b) => a + b, 0);

      card.classList.toggle('bad', !r.ok);
      setTypeColors(card, e.name);
      const q = role => card.querySelector(`[data-role="${role}"]`);
      q('name').textContent = e.name || '（未入力）';
      q('type').textContent = dex ? dex.t1 + (dex.t2 ? '/' + dex.t2 : '') : '—';
      for (let k = 0; k < 6; k++) q('stat' + k).textContent = st ? st[k] : '—';

      const totalEl = q('total');
      totalEl.textContent = total;
      totalEl.classList.toggle('over', total > Engine.rules.maxPointsTotal);
      q('note').textContent = (r.ok && r.members.length > 1) ? 'メガ／非メガの2件を生成' : '';

      const err = q('err');
      err.hidden = r.ok;
      err.textContent = r.ok ? '' : r.error;

      // 上下ボタンは位置で有効・無効が変わる
      const up = card.querySelector('[data-act="up"]');
      const down = card.querySelector('[data-act="down"]');
      if (up) up.disabled = (i === 0);
      if (down) down.disabled = (i === entries.length - 1);
    });

    const allOk = entries.length > 0 && results.every(r => r.ok);
    $('preview').textContent = entriesToText(entries);
    $('count').textContent = `${entries.length} 体`;
    $('save').disabled = !allOk;
    $('download').disabled = !allOk;

    const stEl = $('status');
    if (!entries.length) {
      stEl.className = 'pstat warn';
      stEl.textContent = 'パーティが空です。左の取り込み欄に貼り付けるか、「1体追加」から作ってください。';
    } else if (allOk) {
      const rows = results.reduce((a, r) => a + r.members.length, 0);
      stEl.className = 'pstat';
      stEl.innerHTML = `<b>${entries.length}体</b>すべて有効です（ダメージ表では ${rows} 行として扱われます）。`;
    } else {
      const bad = results.map((r, i) => r.ok ? null : (entries[i].name || `#${i + 1}`)).filter(Boolean);
      stEl.className = 'pstat warn';
      stEl.innerHTML = `入力に問題があります: <b>${esc(bad.join('、'))}</b> — 保存するには全て解消してください。`;
    }
  }

  // ---------------------------------------------------------- 入力

  function onInput(ev) {
    const el = ev.target;
    const i = el.dataset.i, k = el.dataset.k;
    if (i === undefined || !k) return;
    const e = entries[+i];
    if (!e) return;
    if (k.startsWith('pt')) e.points[+k.slice(2)] = el.value.trim();
    else if (k.startsWith('move')) e.moves[+k.slice(4)] = el.value.trim();
    else {
      e[k] = el.value.trim();
      if (k === 'name' || k === 'natureJa') e.importError = null;
    }
    refresh();     // 入力欄は作り直さないので、変換中でも安全
  }

  function onClick(ev) {
    const b = ev.target.closest('button[data-act]');
    if (!b) return;
    const i = +b.dataset.i;
    if (b.dataset.act === 'del') entries.splice(i, 1);
    if (b.dataset.act === 'up' && i > 0) entries.splice(i - 1, 0, entries.splice(i, 1)[0]);
    if (b.dataset.act === 'down' && i < entries.length - 1) entries.splice(i + 1, 0, entries.splice(i, 1)[0]);
    renderList();
  }

  // ---------------------------------------------------------- 起動

  function fillDatalists() {
    const put = (id, items) => {
      $(id).innerHTML = items.map(v => `<option value="${esc(v)}">`).join('');
    };
    put('dl-pokemon', Object.keys(Engine.dex).sort());
    put('dl-moves', Object.keys(Engine.moves).sort());
    put('dl-nature', Object.values(Engine.rules.natureJa));
    // 特性と持ち物も候補を出す。変換の手間が減るし、綴りの揺れも防げる。
    const abilities = new Set();
    Object.values(Engine.dex).forEach(d => (d.ab_list || []).forEach(a => abilities.add(a)));
    Object.keys(Engine.rules.abilities || {}).forEach(a => abilities.add(a));
    put('dl-abilities', [...abilities].sort());
    put('dl-items', [...new Set(Object.values(Engine.rules.itemJa || {}))].sort());
  }

  function loadText(text) {
    entries = textToEntries(text);
    $('src').value = text;
    renderList();
  }

  async function main() {
    const loaded = {};
    for (const n of ['dex', 'moves', 'types', 'rules']) {
      const res = await fetch(`appdata/${n}.json`);
      if (!res.ok) throw new Error(`appdata/${n}.json が読めません`);
      loaded[n] = await res.json();
    }
    Engine.load(loaded);
    fillDatalists();

    const saved = PartyStore.load();
    if (saved) loadText(saved);
    else {
      const res = await fetch('party.txt');
      loadText(res.ok ? await res.text() : '');
    }

    $('list').addEventListener('input', onInput);
    $('list').addEventListener('click', onClick);

    $('apply').addEventListener('click', () => {
      loadText($('src').value);
      flash('取り込みました。内容を確認して保存してください。');
    });

    $('file').addEventListener('change', async (ev) => {
      const f = ev.target.files && ev.target.files[0];
      if (!f) return;
      loadText(await f.text());
      flash(`${f.name} を読み込みました。`);
      ev.target.value = '';
    });

    $('add').addEventListener('click', () => { entries.push(EMPTY()); renderList(); });

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
      loadText(res.ok ? await res.text() : '');
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
