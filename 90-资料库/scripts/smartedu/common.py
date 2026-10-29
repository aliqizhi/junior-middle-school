#!/usr/bin/env python3
"""smartedu 抓取公共库：接口封装 + 下载器"""
import json, os, re, subprocess, time, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(BASE, 'access_token.txt')).read().strip()
S_FILE = ['https://s-file-1.ykt.cbern.com.cn', 'https://s-file-2.ykt.cbern.com.cn']

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36'

def curl_json(url, token=False, retries=3):
    import urllib.request
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'referer': 'https://basic.smartedu.cn/',
                **({'Authorization': f'Bearer {TOKEN}'} if token else {}),
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            if i == retries - 1:
                print(f'  !! JSON失败 {url}: {e}')
                return None
            time.sleep(1.5 * (i + 1))

def get_json_multi(path):
    """parts.json 列出的多 host 地址逐个尝试"""
    for base in S_FILE:
        d = curl_json(base + path)
        if d is not None:
            return d
    return None

def sanitize(name, maxlen=80):
    name = re.sub(r'[\\/:*?"<>|\s]+', '_', str(name)).strip('._')
    return name[:maxlen] if name else 'unnamed'

def download(url, dest, token=True, retries=3):
    """下载文件；统一 X-ND-AUTH 鉴权。已存在且非空则跳过。"""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return 'skip'
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + '.part'
    import urllib.request
    from urllib.parse import urlsplit, urlunsplit, quote
    # 路径含中文等非 ASCII 字符时按段编码
    parts_ = urlsplit(url)
    url = urlunsplit((parts_.scheme, parts_.netloc, quote(parts_.path, safe='/:%'), parts_.query, ''))
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'referer': 'https://basic.smartedu.cn/',
                'X-ND-AUTH': TOKEN,
            })
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(tmp, dest)
            return 'ok'
        except Exception as e:
            if i == retries - 1:
                print(f'  !! 下载失败 {url}: {e}')
                try: os.remove(tmp)
                except OSError: pass
                return 'fail'
            time.sleep(2 * (i + 1))

def fetch_doc_pdf(res_id):
    """取资源详情，返回 (别名, 最佳PDF URL)。"""
    d = curl_json(f'https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/prepare_sub_type/resources/details/{res_id}.json')
    if not d:
        return None, None, None
    alias = (d.get('custom_properties') or {}).get('alias_name') or ''
    title = d.get('title') or ''
    pdf = None
    # 优先 ti_file_flag=pdf 的 PDF
    for ti in d.get('ti_items', []):
        if ti.get('ti_file_flag') == 'pdf' and ti.get('ti_storages'):
            pdf = ti['ti_storages'][0]
            break
    if not pdf:
        # 课件类: flag=pdf 可能没有，取 fmt=pdf
        for ti in d.get('ti_items', []):
            if ti.get('ti_format') == 'pdf' and ti.get('ti_storages'):
                pdf = ti['ti_storages'][0]
                break
    return alias, title, pdf

def tree_nodes(tree_json):
    """树 -> [(node_path, title)] 叶子及中间节点"""
    out = {}
    def walk(n, prefix=()):
        nid = n.get('id')
        if not nid:
            return
        path = prefix + (nid,)
        out['/'.join(path)] = n.get('title') or ''
        for c in (n.get('child_nodes') or []):
            walk(c, path)
    if isinstance(tree_json, list):
        for x in tree_json:
            walk(x)
    else:
        walk(tree_json)
    return out
