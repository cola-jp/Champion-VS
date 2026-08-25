/* ダメージ表と選出補助で共通の小さい描画部品。
 *
 * ここに計算を書かないこと。弱点の中身は Python 側（generate.type_weakness）が出して
 * appdata/threats.json の weak4 / weak2 に入っている。JS で相性表を引き直すと、
 * タイプ別に効く特性（ふゆう・あついしぼう・もふもふ等）の扱いが必ず食い違う。
 */
'use strict';

const UI = (() => {
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* 相手の弱点。4倍と2倍を分けて出す。
     4倍は塗りつぶし、2倍は縁取りにして、数字を読まなくても区別できるようにしてある。
     マルチスケイルやハードロックのような「タイプに依らない」特性は入っていない
     （入れると全部の倍率が動いて弱点表にならない）。 */
  function weakChips(threat, typeColor) {
    const chip = (t, cls) =>
      `<span class="${cls}" style="--tc:${typeColor[t] || '#666'}">${esc(t)}</span>`;
    const x4 = (threat.weak4 || []).map(t => chip(t, 'wk4')).join('');
    const x2 = (threat.weak2 || []).map(t => chip(t, 'wk2')).join('');
    if (!x4 && !x2) return '<span class="wklbl">弱点なし</span>';
    return (x4 ? `<span class="wklbl">×4</span>${x4}` : '')
      + (x2 ? `<span class="wklbl">×2</span>${x2}` : '');
  }

  return { esc, weakChips };
})();
