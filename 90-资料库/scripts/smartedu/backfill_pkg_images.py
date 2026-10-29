#!/usr/bin/env python3
"""阶段2：下载带图题的题包(zip)，提取 question_resource 图片到 91-题库/assets/
输入: /tmp/imgbackfill/scan.jsonl（阶段1产物）
输出: /tmp/imgbackfill/map.jsonl（每行 {nb_path: local_rel}）+ failed_qids.txt
"""
import os, sys, json, io, time, zipfile, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

V = os.path.expanduser('~/workspace/course/junior-middle-school')
T = open(os.path.join(V, '90-资料库/scripts/smartedu/access_token.txt')).read().strip()
OUT = '/tmp/imgbackfill'
ASSETS = os.path.join(V, '91-题库', 'assets')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36'

def http(url, auth=True, timeout=180):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'referer': 'https://basic.smartedu.cn/',
        **({'X-ND-AUTH': T} if auth else {})})
    return urllib.request.urlopen(req, timeout=timeout).read()

def get_json(url):
    return json.loads(http(url).decode('utf-8'))

def job(qid):
    try:
        d = get_json(f'https://s-file-1.ykt.cbern.com.cn/zxx/ndrs/questions/resources/details/{qid}.json')
        zip_url = None
        for ti in d.get('ti_items', []):
            if ti.get('ti_file_flag') == 'offline' and ti.get('ti_storages'):
                zip_url = ti['ti_storages'][0]; break
        if not zip_url:
            return qid, {}, 'no-zip-url'
        blob = http(zip_url)
        zf = zipfile.ZipFile(io.BytesIO(blob))
        found = {}
        for name in zf.namelist():
            if 'question_resource' in name and '/resources/' in name:
                # zip 内路径: [前缀/]_ref/nb_document_parser_api/question_resource/{uuid}/resources/{img}
                tail = name.split('/nb_document_parser_api/')[-1]
                nb_path = '/nb_document_parser_api/' + tail
                local = os.path.join(ASSETS, tail)
                if not os.path.exists(local) or os.path.getsize(local) == 0:
                    os.makedirs(os.path.dirname(local), exist_ok=True)
                    open(local, 'wb').write(zf.read(name))
                found[nb_path] = os.path.relpath(local, os.path.join(V, '91-题库'))
        return qid, found, None
    except Exception as e:
        return qid, {}, f'{type(e).__name__}: {e}'[:120]

# 只处理带图题
qids = []
for line in open(os.path.join(OUT, 'scan.jsonl'), encoding='utf-8'):
    d = json.loads(line)
    if d['imgs']:
        qids.append(d['qid'])
print(f'带图题: {len(qids)}', flush=True)

mapf = open(os.path.join(OUT, 'map.jsonl'), 'a', encoding='utf-8')
failf = open(os.path.join(OUT, 'failed_qids.txt'), 'a', encoding='utf-8')
done = err = imgs = 0
t0 = time.time()
with ThreadPoolExecutor(6) as ex:
    futs = {ex.submit(job, q): q for q in qids}
    for f in as_completed(futs):
        qid, found, error = f.result()
        if error:
            err += 1; failf.write(f'{qid}\t{error}\n'); failf.flush()
        else:
            done += 1; imgs += len(found)
            if found:
                mapf.write(json.dumps(found, ensure_ascii=False) + '\n'); mapf.flush()
        alld = done + err
        if alld % 200 == 0:
            print(f'进度 {alld}/{len(qids)} | 成功 {done} 失败 {err} | 提取图片 {imgs} | {time.time()-t0:.0f}s', flush=True)
mapf.close(); failf.close()
print(f'完成: 题包成功 {done} 失败 {err}，提取图片 {imgs}，耗时 {time.time()-t0:.0f}s', flush=True)
