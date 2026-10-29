#!/usr/bin/env python3
"""
国平台题库配图批量回填
前置：in-app 浏览器打开 basic.smartedu.cn（登录态），导出 cookie 存为 cookies_new.txt
用法：
  python3 backfill_images.py ~/Downloads/cookies_new.txt
流程：
  1. 扫描 91-题库/ 全部 md 中的图片引用（unique URL）
  2. 带浏览器 cookie 下载到 91-题库/assets/{uuid}/{img}
  3. 改写 md 引用为本地相对路径
  4. 输出报告（成功/失败清单）
"""
import os, re, sys, time, hashlib, urllib.request, concurrent.futures as cf

V = os.path.expanduser('~/workspace/course/junior-middle-school')
QB = os.path.join(V, '91-题库')
ASSETS = os.path.join(QB, 'assets')
COOKIE_FILE = sys.argv[1] if len(sys.argv) > 1 else '/tmp/smartedu/cookies_new.txt'
cookie = open(COOKIE_FILE).read().strip()
HEADERS = {
    'Cookie': cookie,
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
    'Referer': 'https://basic.smartedu.cn/',
    'X-ND-AUTH': open(os.path.join(V, '90-资料库/scripts/smartedu/access_token.txt')).read().strip(),
}
PAT = re.compile(r'\(https://basic\.smartedu\.cn(/nb_document_parser_api/question_resource/([0-9a-f-]+)/resources/([^)]+))\)')
REF = re.compile(r'https://basic\.smartedu\.cn(/nb_document_parser_api/question_resource/([0-9a-f-]+)/resources/([^)\s]+))')

def fetch(url, dest, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            data = urllib.request.urlopen(req, timeout=30).read()
            if len(data) > 2000 and not data.lstrip().startswith(b'<!doctype'):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                open(dest, 'wb').write(data)
                return True
            return False  # WAF/错误页
        except Exception:
            time.sleep(1 + i)
    return False

# 1) 收集引用
refs = {}  # path -> set of md files
for root, _, files in os.walk(QB):
    if 'assets' in root: continue
    for f in files:
        if not f.endswith('.md'): continue
        p = os.path.join(root, f)
        for m in REF.finditer(open(p, encoding='utf-8').read()):
            refs.setdefault(m.group(1), set()).add(p)
print(f'待回填图片: {len(refs)} 张（引用 {sum(len(v) for v in refs.values())} 处）')

# 2) 并发下载
def job(item):
    path, mds = item
    dest = os.path.join(ASSETS, path.split('/nb_document_parser_api/question_resource/')[1].lstrip('/'))
    return (path, mds, fetch('https://basic.smartedu.cn' + path, dest))

ok = fail = 0
failed = []
with cf.ThreadPoolExecutor(max_workers=8) as ex:
    for path, mds, success in ex.map(job, list(refs.items())):
        if success: ok += 1
        else: fail += 1; failed.append(path)
print(f'下载完成: 成功 {ok} / 失败 {fail}')

# 3) 改写 md 引用为本地相对路径
def local_rel(md_path, res_path):
    rel_tail = res_path.split('/nb_document_parser_api/question_resource/')[1].lstrip('/')
    depth = len(os.path.relpath(md_path, QB).split(os.sep)) - 1
    return os.path.relpath(os.path.join(ASSETS, rel_tail), os.path.dirname(md_path))

changed = 0
for root, _, files in os.walk(QB):
    if 'assets' in root: continue
    for f in files:
        if not f.endswith('.md'): continue
        p = os.path.join(root, f)
        t = open(p, encoding='utf-8').read()
        t2 = REF.sub(lambda m: f'({local_rel(p, m.group(1))})', t)
        if t2 != t:
            open(p, 'w', encoding='utf-8').write(t2)
            changed += 1
print(f'改写 md: {changed} 个文件')

if failed:
    fl = os.path.join(V, '90-资料库', 'scripts', 'smartedu', 'failed_images.txt')
    open(fl, 'w').write('\n'.join(failed))
    print(f'失败清单 → {fl}')
