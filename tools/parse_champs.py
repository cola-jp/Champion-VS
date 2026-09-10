# -*- coding: utf-8 -*-
"""champs.pokedb.tokyo の使用率ページを、既存の data/usage.json と同じ形に変換する。

pkmnchamps.com が更新停止したので、その後継として使う。
大きな違いが2つあるので注意すること。

1. 名前が日本語。pkmnchamps は英語スラッグ（earthquake / rough-skin）だったので
   MOVE_NAME_EN_JA と ABILITY_JA を通して和訳していたが、こちらは最初から日本語。
   data/moves.csv も data/dex.csv も日本語キーなので、変換は不要。
   generate.py 側で「日本語で来る」パスを用意すること。

2. 能力ポイントが「努力値」ではなく「ポイント（0〜32）」で出ている。
   party.py が使っている単位そのものなので、EVからの換算が要らない。
   しかも報告率の合計がほぼ100%になり、pkmnchamps の spreads（上位12件だけで
   合計71.5%）のような取りこぼしが無い。型シェアの割り直しが不要になる。
"""
import json
import re
import sys

from bs4 import BeautifulSoup

STAT_LETTERS = {'H': 'hp', 'A': 'atk', 'B': 'def', 'C': 'spa', 'D': 'spd', 'S': 'spe'}


def _usage_list(soup, heading):
    """「リストを表示」の中の <li class="usage-list-item"> を [(名前, 割合)] で返す。"""
    for h3 in soup.select('h3'):
        if h3.get_text(strip=True) != heading:
            continue
        box = h3.find_parent(class_='card-content')
        if not box:
            continue
        out = []
        for li in box.select('li.usage-list-item'):
            name = li.select_one('.usage-name')
            rate = li.select_one('.usage-rate')
            if not name or not rate:
                continue
            try:
                pct = float(rate.get_text(strip=True).rstrip('%'))
            except ValueError:
                continue
            out.append((name.get_text(strip=True), pct))
        return out
    return []


def _moves(soup):
    """技だけは「リストを表示」ではなく専用のバー表示。
    <div class="pokemon-trend__move-item"> の name と rate を拾う。"""
    for h3 in soup.select('h3'):
        if h3.get_text(strip=True) != '技':
            continue
        box = h3.find_parent(class_='card-content')
        if not box:
            continue
        out = []
        for it in box.select('.pokemon-trend__move-item'):
            name = it.select_one('.pokemon-trend__move-name')
            rate = it.select_one('.pokemon-trend__move-rate')
            if not name or not rate:
                continue
            try:
                pct = float(rate.get_text(strip=True).rstrip('% ').strip())
            except ValueError:
                continue
            out.append((name.get_text(strip=True), pct))
        return out
    return []


def _spreads(soup):
    """能力ポイントを [{'label','usage','points'}] で返す。

    このサイトは「AS 41.6%」という型のまとまりと、その内訳（AS + h 29.8% など）を
    入れ子で持っている。内訳のほうが実際の振り分けなので、そちらを採用する。
    単位はポイント（0〜32・合計66）で、party.py の単位そのまま。EV換算は不要。
    """
    for h3 in soup.select('h3'):
        if h3.get_text(strip=True) != '能力ポイント':
            continue
        box = h3.find_parent(class_='card-content')
        if not box:
            continue
        out = []
        for det in box.select('.pokemon-stat-spread__detail'):
            name = det.select_one('.pokemon-stat-spread__detail-name')
            rate = det.select_one('.pokemon-stat-spread__detail-rate')
            if not name or not rate:
                continue
            try:
                usage = float(rate.get_text(strip=True).rstrip('%'))
            except ValueError:
                continue
            pts = {}
            chips = det.select('.pokemon-stat-spread__chip')
            for chip in chips:
                t = chip.get_text(' ', strip=True)
                m = re.match(r'^([HABCDS])\s*(\d+)$', t.replace('\u3000', ' ').replace(' ', ''))
                if m:
                    pts[STAT_LETTERS[m.group(1)]] = int(m.group(2))
            if pts:
                out.append({'label': name.get_text(strip=True), 'usage': usage, 'points': pts})
        if out:
            return out
        # 内訳が無い（1種類しか無い）ポケモン用のフォールバック
        for li in box.select('li.usage-list-item--stats'):
            text = li.get_text(' ', strip=True)
            m = re.search(r'([\d.]+)%', text)
            if not m:
                continue
            pts = {}
            for letter, val in re.findall(r'\b([HABCDS])\s+(\d+)\b', text):
                pts[STAT_LETTERS[letter]] = int(val)
            if pts:
                out.append({'label': text.split()[1] if len(text.split()) > 1 else '',
                            'usage': float(m.group(1)), 'points': pts})
        return out
    return []


def _teammates(soup):
    for h3 in soup.select('h3'):
        if h3.get_text(strip=True) != '同じチーム':
            continue
        box = h3.find_parent(class_='card-content')
        if not box:
            continue
        return [n.get_text(strip=True) for n in box.select('.usage-name')]
    return []


def parse_detail(html, rank=None):
    soup = BeautifulSoup(html, 'lxml')
    title = soup.select_one('p.title')
    name = title.get_text(strip=True) if title else ''
    return {
        'pick_rank': rank,
        'name': name,
        'moves': [{'name': n, 'usage': u} for n, u in _moves(soup)],
        'abilities': [{'name': n, 'usage': u} for n, u in _usage_list(soup, '特性')],
        'items': [{'name': n, 'usage': u} for n, u in _usage_list(soup, '持ち物')],
        'natures': [{'name': re.sub(r'\(.*\)', '', n), 'usage': u}
                    for n, u in _usage_list(soup, '能力補正')],
        'spreads': _spreads(soup),
        'teammates': _teammates(soup),
    }


def parse_list(html):
    """一覧ページから [(順位, 名前, 詳細パス)] を返す。順位が「-」の行は捨てる。"""
    soup = BeautifulSoup(html, 'lxml')
    out = []
    for a in soup.select('a[href^="/pokemon/show/"]'):
        text = a.get_text(' ', strip=True)
        m = re.match(r'^(\d+)\s+(.+)$', text)
        if not m:
            continue
        out.append((int(m.group(1)), m.group(2), a['href']))
    return out


if __name__ == '__main__':
    mode, path = sys.argv[1], sys.argv[2]
    html = open(path, encoding='utf-8').read()
    data = parse_list(html) if mode == 'list' else parse_detail(html)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
