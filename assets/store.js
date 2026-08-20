/* 登録したパーティの保存先。party.html と index.html で共有する。
 * 中身は party.txt と同じテキストそのまま。別形式にすると取り込み・書き出しと
 * ズレるので、保存も同じフォーマットで持つ。 */
'use strict';

const PartyStore = (() => {
  const KEY = 'championvs.party';

  function load() {
    try {
      return localStorage.getItem(KEY) || null;
    } catch (e) {
      return null;   // プライベートモード等で localStorage が使えない場合
    }
  }

  function save(text) {
    try {
      localStorage.setItem(KEY, text);
      return true;
    } catch (e) {
      return false;
    }
  }

  function clear() {
    try {
      localStorage.removeItem(KEY);
    } catch (e) { /* 消せなくても致命的ではない */ }
  }

  /* ブラウザにファイルを保存させる。単一HTMLをやめたのでこれが使える。 */
  function download(text, filename) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'party.txt';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return { load, save, clear, download, KEY };
})();
