#!/usr/bin/env python3
"""
data/特性の効果.pdf から data/abilities_ja.json を作り直す。

    pip install pypdf
    python build/extract_abilities.py

出典は「ポケモンチャンピオンズ育成考察 Wiki」の特性一覧ページを PDF 保存したもの。
ページを更新したら PDF を置き換えてこのスクリプトを流す。

通常のビルド（build/generate.py）はこのスクリプトを呼ばない。生成済みの
data/abilities_ja.json だけを読むので、ビルドに pypdf は要らない。
"""
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(ROOT, 'data', '特性の効果.pdf')
OUT = os.path.join(ROOT, 'data', 'abilities_ja.json')

# 見出しは「特性名 [ 編集]」の形。名前の末尾の "?" はWiki側の未作成リンク印なので落とす。
HEADER = re.compile(r'^(.+?)(\?)?\s*\[\s*編集\s*\]\s*$', re.M)
# 五十音の索引見出し。特性そのものではないので飛ばす。
ROW_HEADERS = {f'{k}行' for k in 'アカサタナハマヤラワ'} | {'A~Z'}


def extract_text():
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit('pypdf が要ります: pip install pypdf')
    reader = PdfReader(PDF)
    # PDFのフォントは康熙部首（⼤ ⼒ ⾃ …）を使っていて、そのままだと図鑑側の
    # 特性名と文字列比較ができない。NFKCで通常の漢字に揃える。
    return unicodedata.normalize('NFKC', '\n'.join(p.extract_text() for p in reader.pages))


def parse(text):
    marks = [(m.start(), m.end(), m.group(1).strip()) for m in HEADER.finditer(text)]
    names = [m[2] for m in marks]
    # ページ前半はカテゴリ別の解説、'A~Z' 以降が特性ごとの本文。'その他' 以降は付録。
    lo = names.index('A~Z')
    hi = names.index('その他')

    out = {}
    for i in range(lo, hi):
        start, end, name = marks[i]
        if name in ROW_HEADERS:
            continue
        tail = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        lines = [l.strip() for l in text[end:tail].splitlines() if l.strip()]
        lines = [l for l in lines if not l.startswith('特性の効果 -')]   # ページ見出しの混入
        if lines:
            out[name] = lines[0]      # 1行目がその特性の主効果。細かい例外は元PDFを見る
    return out


def main():
    abilities = parse(extract_text())
    if len(abilities) < 200:
        sys.exit(f'抽出できた特性が {len(abilities)} 件しかありません。PDFの構造が変わった可能性があります。')
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(abilities, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    print(f'書き出し完了: {OUT}  ({len(abilities)} 件)')


if __name__ == '__main__':
    main()
