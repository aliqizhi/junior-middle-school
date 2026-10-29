#!/usr/bin/env python3
"""阶段1：扫描全部题目的 item.json，建立 qid→(题干文本, 图片引用, 渲染图URL) 映射
输出: /tmp/imgbackfill/scan.jsonl（每行一题）+ 控制台统计
"""
import os, sys, json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

V = os.path.expanduser('~/workspace/course/junior-middle-school')
T = open(os.path.join(V, '90-资料库/scripts/smartedu/access_token.txt')).read().strip()
OUT = '/tmp/imgbackfill'
os.makedirs(OUT, exist_ok=True)
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36'

def get_json(url, auth=False, retries=2):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA, 'referer': 'https://basic.smartedu.cn/',
                **({'X-ND-AUTH': T} if auth else {})})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            if i == retries - 1: return None
            time.sleep(1 + i)
    return None

# 读 manifest（去重 qid → book）
qids = {}
man = os.path.join(V, '90-资料库/scripts/smartedu/questions_manifest.jsonl')
if not os.path.exists(man):
    # 兼容：从 /tmp 抢救
    man = '/tmp/smartedu/out/questions_manifest.jsonl'
for line in open(man, encoding='utf-8'):
    try:
        d = json.loads(line)
        qids.setdefault(d['qid'], d.get('book', ''))
    except Exception: pass
print(f'manifest 去重题数: {len(qids)}', flush=True)

def probe(item):
    qid, book = item
    d = get_json(f'https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/questions/resources/details/{qid}.json')
    if not d: return None
    rec = {'qid': qid, 'book': book, 'imgs': [], 'render': None, 'stem': ''}
    for ti in d.get('ti_items', []):
        st = ti.get('ti_storages') or []
        if st and 'item.json' in st[0]:
            q = get_json(st[0], auth=True)
            if not q: continue
            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items(): walk(v)
                elif isinstance(o, list):
                    for v in o: walk(v)
                elif isinstance(o, str):
                    for m in re.finditer(r'(?:https://basic\.smartedu\.cn)?(/nb_document_parser_api/question_resource/[^"\')\s]+)', o):
                        rec['imgs'].append(m.group(1))
                    if 'question_resource' in o and not rec['imgs']:
                        for m in re.finditer(r'question_resource/([0-9a-f-]+)/resources/([^"\')\s]+)', o):
                            rec['imgs'].append(m.group(0))
            walk(q)
            # 题干文本（去标签）用于 md 定位
            for it2 in (q.get('items') or []):
                rec['stem'] = re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', it2.get('prompt') or ''))
                if rec['stem']: break
        if st and 'mainbig' in st[0]:
            rec['render'] = st[0]
    if not rec['render']:
        cp = (d.get('custom_properties') or {}).get('preview') or {}
        rec['render'] = cp.get('question_big')
    return rec

tasks = list(qids.items())
done = err = 0
out = open(os.path.join(OUT, 'scan.jsonl'), 'w', encoding='utf-8')
t0 = time.time()
with ThreadPoolExecutor(12) as ex:
    futs = {ex.submit(probe, t): t[0] for t in tasks}
    for f in as_completed(futs):
        try:
            r = f.result()
            if r is None: err += 1
            else:
                out.write(json.dumps(r, ensure_ascii=False) + '\n'); done += 1
        except Exception: err += 1
        done_all = done + err
        if done_all % 2000 == 0:
            print(f'进度 {done_all}/{len(tasks)}  {time.time()-t0:.0f}s', flush=True)
out.close()
print(f'完成: 成功 {done} 失败 {err}，耗时 {time.time()-t0:.0f}s', flush=True)
