#!/usr/bin/env python3
"""阶段3：用 map.jsonl 把 91-题库 md 里的平台图片引用改写为本地相对路径"""
import os, json

V = os.path.expanduser('~/workspace/course/junior-middle-school')
QB = os.path.join(V, '91-题库')
MAP = '/tmp/imgbackfill/map.jsonl'

mapping = {}
for line in open(MAP, encoding='utf-8'):
    d = json.loads(line)
    mapping.update(d)
print(f'映射条目: {len(mapping)}')

changed = miss = 0
miss_list = []
for root, _, files in os.walk(QB):
    if 'assets' in root: continue
    for f in files:
        if not f.endswith('.md'): continue
        p = os.path.join(root, f)
        t = open(p, encoding='utf-8').read()
        t2 = t
        # 找出本文件用到的映射
        import re
        for m in set(re.findall(r'https://basic\.smartedu\.cn(/nb_document_parser_api/question_resource/[^)\s]+)', t)):
            if m in mapping:
                rel = os.path.relpath(os.path.join(QB, mapping[m]), os.path.dirname(p))
                t2 = t2.replace(f'https://basic.smartedu.cn{m}', rel)
            else:
                miss += 1
                miss_list.append((os.path.relpath(p, QB), m[:80]))
        if t2 != t:
            open(p, 'w', encoding='utf-8').write(t2)
            changed += 1
print(f'改写 md: {changed} 个文件 | 未命中引用: {miss} 处')
if miss_list:
    with open('/tmp/imgbackfill/unresolved.txt', 'w', encoding='utf-8') as f:
        for p, m in miss_list[:200]:
            f.write(f'{p}\t{m}\n')
    print('未命中清单 → /tmp/imgbackfill/unresolved.txt')
