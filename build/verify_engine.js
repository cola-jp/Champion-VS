#!/usr/bin/env node
/*
 * assets/engine.js（JS移植版）が Python 版と同じ数字を出すか確かめる。
 *
 *     node build/verify_engine.js
 *
 * appdata/golden.json には build/export_app_data.py が Python の実装で計算した
 * 期待値が入っている。ブラウザを開かなくても、この1コマンドで移植の壊れを検出できる。
 * 数字を扱うコードを触ったら必ず流すこと。
 */
'use strict';

const fs = require('fs');
const path = require('path');
const Module = require('module');

const ROOT = path.dirname(__dirname);

function loadEngine() {
  // engine.js はブラウザ用の素のスクリプト（module 構文なし）なので、
  // 末尾に export を足して CommonJS として読み込む。
  const src = fs.readFileSync(path.join(ROOT, 'assets', 'engine.js'), 'utf8')
            + '\nmodule.exports = Engine;\n';
  const m = new Module('engine.js', null);
  m._compile(src, path.join(ROOT, 'assets', 'engine.js'));
  return m.exports;
}

function readJson(name) {
  const p = path.join(ROOT, 'appdata', name);
  if (!fs.existsSync(p)) {
    console.error(`${p} がありません。先に python build/export_app_data.py を流してください。`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function main() {
  const Engine = loadEngine();
  const data = {
    dex: readJson('dex.json'),
    moves: readJson('moves.json'),
    types: readJson('types.json'),
    rules: readJson('rules.json'),
  };
  const threats = readJson('threats.json');
  const golden = readJson('golden.json');

  Engine.load(data);
  const res = Engine.selfTest(golden, threats);

  console.log(`相手 ${threats.length} 行 / 期待値 ${golden.rows.length} 行`);
  console.log(`突き合わせた項目: ${res.checked} 件`);

  if (res.issues.length === 0) {
    console.log('一致: JS版とPython版で同じ数値が出ています');
    return;
  }
  console.error(`不一致 ${res.issues.length} 件:`);
  res.issues.slice(0, 40).forEach(i => console.error('  ' + i));
  if (res.issues.length > 40) console.error(`  … 他 ${res.issues.length - 40} 件`);
  process.exit(1);
}

main();
