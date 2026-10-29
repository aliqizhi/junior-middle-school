#!/usr/bin/env python3
"""抓取「在线练习」题库：题目+选项+答案+解析 -> Markdown（按章节组织）
输出: ~/Downloads/00.中考/08.国平台智慧教育/题库/<学科>/<年级·版本>/<章节>.md
"""
import os, sys, json, re, time, html as htmlmod
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import curl_json, get_json_multi, sanitize

OUT_ROOT = os.path.expanduser('~/Downloads/00.中考/08.国平台智慧教育/题库')
MANIFEST = '/tmp/smartedu/out/questions_manifest.jsonl'
os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)

# 沪系教材中静态题库有题的书目
BOOKS = [
    # 学科, 年级册别, 版本, book_id, 备注
    ('物理', '八年级全一册', '沪科技版2024新教材', '7d387123-ff96-4bd1-9409-97503915297b'),
    ('物理', '九年级全一册', '沪科技版2024新教材', '5744e08f-a1c2-46c0-8620-492ec3cd5538'),
    ('化学', '九年级上册', '沪教版(上海)', '2f03ebd3-c265-b24e-7ac0-8505cace3ad0'),
    ('数学', '七年级上册', '沪科技版2024新教材', '10662247-9106-4d40-9a97-53de801855f8'),
    ('数学', '七年级下册', '沪科技版2024新教材', '6e3974a3-0f6e-480e-a119-bbc16b697dfc'),
]

SUB = str.maketrans('0123456789+-=()', '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎')
SUP = str.maketrans('0123456789+-=()', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾')

def html2text(s):
    if not s:
        return ''
    s = re.sub(r'<sub>([^<]*)</sub>', lambda m: m.group(1).translate(SUB), s)
    s = re.sub(r'<sup>([^<]*)</sup>', lambda m: m.group(1).translate(SUP), s)
    s = re.sub(r'<img[^>]*src="([^"]*)"[^>]*>', lambda m: f'\n![]({m.group(1)})\n', s)
    s = re.sub(r'</(p|div|br|h\d|li|tr)>', '\n', s)
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = htmlmod.unescape(s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def tag_names(it, dim=None):
    out = []
    for t in it.get('tag_list', []):
        if dim is None or t['tag_dimension_id'] == dim:
            out.append(t['tag_name'])
    return out

def parse_item(qjson):
    """item.json -> (题干, [选项], [答案], 解析)"""
    prompts, choices, answers, feeds = [], [], [], []
    for it in (qjson.get('items') or []):
        p = html2text(it.get('prompt'))
        if p:
            prompts.append(p)
        for c in (it.get('choices') or []):
            t = html2text(c.get('text'))
            if t:
                choices.append(f"{c.get('identifier', '')}. {t}")
    for r in (qjson.get('responses') or []):
        if r.get('corrects'):
            answers.append('/'.join(str(x) for x in r['corrects']))
    for f in (qjson.get('feedbacks') or []):
        c = html2text(f.get('content'))
        if c:
            feeds.append(c)
    return '\n\n'.join(prompts), choices, answers, '\n\n'.join(feeds)


def fetch_question(qid):
    """返回 dict(stem/choices/answers/feed/preview/title) 或 None"""
    d = curl_json(f'https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/questions/resources/details/{qid}.json')
    if not d:
        return None
    url = preview = None
    # flag=href/source 的 ti_item 即 item.json（ti_format 值不固定）
    for want in ('href', 'source'):
        for ti in d.get('ti_items', []):
            if ti.get('ti_file_flag') == want and ti.get('ti_storages'):
                u = ti['ti_storages'][0]
                if 'item.json' in u:
                    url = u
                    break
        if url:
            break
    if not url:
        for ti in d.get('ti_items', []):
            if ti.get('ti_storages') and 'item.json' in ti['ti_storages'][0]:
                url = ti['ti_storages'][0]
                break
    for ti in d.get('ti_items', []):
        if ti.get('ti_file_flag') == 'thumbnail_1' and ti.get('ti_storages'):
            preview = ti['ti_storages'][0]
            break
    if not url:
        return None
    q = curl_json(url)
    if not q:
        return None
    stem, choices, answers, feed = parse_item(q)
    return {
        'stem': stem, 'choices': choices, 'answers': answers, 'feed': feed,
        'preview': preview, 'title': (d.get('title') or '').strip(),
    }


def run_book(book):
    subj, grade, ver, bid = book
    tree = get_json_multi(f'/zxx/ndrs/questions/trees/{bid}.json')
    id2title = {}
    def walk(ns):
        for n in ns:
            id2title[n.get('id')] = (n.get('title') or '').strip()
            walk(n.get('child_nodes') or [])
    walk(tree or [])

    parts = get_json_multi(f'/zxx/ndrs/questions/teachingmaterials/{bid}/resources/parts.json') or []
    qs = []
    for purl in parts:
        d = curl_json(purl)
        if d:
            qs += d
    print(f'== {subj} {grade} {ver}: 题目 {len(qs)}')

    by_ch = defaultdict(list)
    seen_q = set()
    for q in qs:
        if q['id'] in seen_q:
            continue
        seen_q.add(q['id'])
        # 题目可能挂在多本教材下：取本书对应的 chapter_path
        tm = q.get('teachmeterial_ids') or []
        try:
            idx = tm.index(bid)
        except ValueError:
            idx = 0
        cps = q.get('chapter_paths') or ['']
        cp = cps[idx] if idx < len(cps) else (cps[0] if cps else '')
        leaf = cp.split('/')[-1] if cp else ''
        if leaf and leaf in id2title:
            key = ('章节', '/'.join(id2title.get(nid, nid) for nid in cp.split('/')), cp)
        else:
            # 旧目录题目：按知识点归类
            kps = (q.get('custom_properties') or {}).get('qb_knowledge_points') or []
            key = ('知识点', kps[0] if kps else '未分类', '')
        by_ch[key].append(q)

    man = open(MANIFEST, 'a', encoding='utf-8')
    total_md = 0
    for (kind, ch_name, ch_path), qlist in sorted(by_ch.items()):
        if kind == '章节':
            ch_dir = '/'.join(sanitize(t[:50]) for t in ch_name.split('/'))
            head_title = ch_name.split('/')[-1]
        else:
            ch_dir = f'知识点归类/{sanitize(ch_name[:50])}'
            head_title = f'知识点·{ch_name}'
        dest_dir = os.path.join(OUT_ROOT, sanitize(subj), f'{sanitize(grade)}·{sanitize(ver)}')
        md_path = os.path.join(dest_dir, f'{ch_dir}.md')
        os.makedirs(os.path.dirname(md_path), exist_ok=True)

        # 并发取题目内容
        results = [None] * len(qlist)
        with ThreadPoolExecutor(6) as ex:
            futs = {ex.submit(fetch_question, q['id']): i for i, q in enumerate(qlist)}
            for f in as_completed(futs):
                i = futs[f]
                try:
                    results[i] = f.result()
                except Exception:
                    results[i] = None
        lines = [f'# {head_title}（同步练习）', '',
                 f'> 教材：{subj}·{grade}·{ver} ｜ 来源：国家中小学智慧教育平台·在线练习 ｜ 共 {len(qlist)} 题', '']
        ok_cnt = 0
        for i, (q, r) in enumerate(zip(qlist, results), 1):
            qtype = next((t for t in tag_names(q) if t in ('单选题','多选题','填空题','解答题','判断题','选择题')), '')
            diff = next((t for t in tag_names(q) if t in ('非常简单','简单','适中','较难','难','非常难')), '')
            head = f'## {i}. {qtype}' + (f'（难度：{diff}）' if diff else '')
            lines.append(head); lines.append('')
            if r is None:
                lines.append(f'（题目 {q["id"]} 内容获取失败，题干：{sanitize(q.get("title"))[:80]}）'); lines.append('')
                man.write(json.dumps({'book': bid, 'qid': q['id'], 'status': 'fail'}, ensure_ascii=False) + '\n')
                continue
            stem, choices, answers, feed, preview, qtitle = (r.get('stem'), r.get('choices'),
                r.get('answers'), r.get('feed'), r.get('preview'), r.get('title'))
            body = stem or qtitle or ''
            lines.append(body); lines.append('')
            if not stem and preview:
                lines.append(f'![题目配图]({preview})'); lines.append('')
            if choices:
                lines += [f'- {c}' for c in choices]; lines.append('')
            if answers:
                lines.append(f'【答案】{"，".join(answers)}'); lines.append('')
            if feed:
                lines.append(f'【解析】{feed}'); lines.append('')
            ok_cnt += 1
            man.write(json.dumps({'book': bid, 'qid': q['id'], 'status': 'ok', 'chapter': ch_dir}, ensure_ascii=False) + '\n')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        total_md += 1
        print(f'   {ch_dir}: {ok_cnt}/{len(qlist)} 题')
    man.close()


def main():
    # 校正数学书目 id
    qitems = []
    for i in [100, 101, 102, 103]:
        try:
            qitems += json.load(open(f'/tmp/smartedu/q_part_{i}.json'))
        except Exception:
            pass
    def find_book(kw):
        for it in qitems:
            if kw in (it.get('title') or ''):
                return it['id']
        return None
    fixes = {
        '新教材-初中数学沪科技版七年级上册': ('数学', '七年级上册', '沪科技版2024新教材'),
        '新教材-初中数学沪科技版七年级下册': ('数学', '七年级下册', '沪科技版2024新教材'),
        '初中英语沪教版九年级上册': ('英语', '九年级上册', '沪教版(上海)'),
        '初中英语沪教版九年级下册': ('英语', '九年级下册', '沪教版(上海)'),
        '初中英语沪教版八年级上册': ('英语', '八年级上册', '沪教版(上海)'),
        '初中英语沪教版八年级下册': ('英语', '八年级下册', '沪教版(上海)'),
    }
    books = []
    for title_kw, (subj, grade, ver) in fixes.items():
        bid = find_book(title_kw)
        if bid:
            books.append((subj, grade, ver, bid))
    # 物理两本已有 id，加上
    books += [b for b in BOOKS if b[0] == '物理' or b[0] == '化学']
    print('书目:', [(b[0], b[1], b[3][:8]) for b in books])
    for b in books:
        t0 = time.time()
        run_book(b)
        print(f'== {b[0]}{b[1]} 完成 {time.time()-t0:.0f}s')
    print('Q DONE')

if __name__ == '__main__':
    main()
