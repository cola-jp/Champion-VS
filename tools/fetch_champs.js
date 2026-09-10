// champs.pokedb.tokyo の使用率を上位150体ぶん巡回し、必要な部分だけ抜いて保存する。
//
// 使い方
//   1. https://champs.pokedb.tokyo/pokemon/list?season=6&rule=0 を開く
//   2. 開発者ツール(F12)のコンソールにこのファイルの中身を貼って実行
//   3. 数分待つと champs_s6_raw.json がダウンロードされる
//
// ページ内から fetch するので Referer / Origin が正しく付き、Forbidden にならない。
// 詳細ページは1体あたり0.5〜1.3MBあるが、必要な6ブロックだけ切り出して保持するので
// 手元に残るのは1体あたり数十KB。ブラウザがメモリを抱え込まずに済む。
(async () => {
  const TOP  = 150;   // 何位まで取るか
  const WAIT = 400;   // 1件あたりの待ち時間(ms)

  // 詳細ページから残すセクション。これ以外（構築記事・倒した技など）は捨てる
  const KEEP = ['技', '特性', '持ち物', '能力補正', '能力ポイント', '同じチーム'];

  function slim(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const parts = [];
    const title = doc.querySelector('p.title');
    if (title) parts.push(`<p class="title">${title.textContent.trim()}</p>`);
    for (const h3 of doc.querySelectorAll('h3')) {
      if (!KEEP.includes(h3.textContent.trim())) continue;
      const card = h3.closest('.card-content');
      if (card) parts.push(card.outerHTML);
    }
    return parts.join('\n');
  }

  const links = [...document.querySelectorAll('a[href^="/pokemon/show/"]')]
    .map(a => ({ text: a.textContent.replace(/\s+/g, ' ').trim(), href: a.getAttribute('href') }))
    .map(x => { const m = x.text.match(/^(\d+)\s+(.+)$/); return m ? { rank: +m[1], name: m[2], href: x.href } : null; })
    .filter(Boolean)
    .filter(x => x.rank <= TOP)
    .sort((a, b) => a.rank - b.rank);

  console.log(`対象 ${links.length} 体 / 想定 約${Math.round(links.length * WAIT / 1000 / 60 * 10) / 10}分`);
  const out = { season: 6, rule: 0, fetched_at: new Date().toISOString(), details: [] };
  const failed = [];

  for (const [i, x] of links.entries()) {
    try {
      const res = await fetch(x.href, { headers: { accept: 'text/html' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      out.details.push({ rank: x.rank, name: x.name, href: x.href, html: slim(await res.text()) });
    } catch (e) {
      failed.push(`${x.rank} ${x.name}: ${e.message}`);
    }
    if (i % 10 === 0) console.log(`${i + 1}/${links.length}  ${x.name}`);
    await new Promise(r => setTimeout(r, WAIT));
  }

  const json = JSON.stringify(out);
  console.log(`完了 ${out.details.length}体 / 約${Math.round(json.length / 1024 / 1024 * 10) / 10}MB`);
  if (failed.length) console.warn('取得できなかったもの:', failed);

  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([json], { type: 'application/json;charset=utf-8' }));
  a.download = 'champs_s6_raw.json';
  a.click();
})();
