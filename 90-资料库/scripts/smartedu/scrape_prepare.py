#!/usr/bin/env python3
"""抓取「教师备课授课」资料：课程包内的 教学设计/课件/学习任务单/课后练习 PDF（忽略视频）
输出: ~/Downloads/00.中考/08.国平台智慧教育/备课资料/<学科>/<年级册别·版本>/<章节>/<序>_<课题>_<类型>.pdf
清单: /tmp/smartedu/out/prepare_manifest.jsonl
"""
import os, sys, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import curl_json, get_json_multi, sanitize, download, fetch_doc_pdf, tree_nodes

OUT_ROOT = os.path.expanduser('~/Downloads/00.中考/08.国平台智慧教育/备课资料')
MANIFEST = '/tmp/smartedu/out/prepare_manifest.jsonl'
os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)

# 沪教版（五四学制）教材 —— 优先当前年级（九年级），其次八年级；跨学科取生物/地理
BOOKS = [
    # 学科, 年级册别, 版本说明, book_id, 优先级
    ('数学', '九年级上册', '沪教版五四制', '4d9adf9b-80c7-429d-8c2f-1b651ad2d1ed', 1),
    ('数学', '九年级下册', '沪教版五四制', '4709c8f4-1eef-4292-a848-fb463347eeb4', 1),
    ('化学', '九年级上册', '沪教版五四制', '1ce5758d-d045-4c92-a8ce-153e7252dfbf', 1),
    ('化学', '九年级下册', '沪教版五四制', 'bdfd36de-c60a-45ba-a2d8-122051c49542', 1),
    ('物理', '九年级上册', '沪教版五四制', '9099080f-ca20-40db-acf4-cd373be97edd', 1),
    ('物理', '九年级下册', '沪教版五四制', 'ab7407b2-4822-4218-a909-cb8f4b6d141b', 1),
    ('数学', '八年级上册', '沪教版五四制', '561056b2-29a1-4588-9ed2-a9440667e589', 2),
    ('数学', '八年级下册', '沪教版五四制', 'e6c6ae5b-35f0-4ecd-a80d-0800fbe11c87', 2),
    ('物理', '八年级上册', '沪教版五四制', 'c2e70bc6-88ff-4310-bf30-d141fe5dd21f', 2),
    ('物理', '八年级下册', '沪教版五四制', 'a41e0eae-a18d-47fd-85d2-9160b438dfc6', 2),
    ('生物学', '八年级上册', '沪教版五四制', 'fb31aef0-4662-8039-53be-7f010e662b22', 3),
    ('生物学', '八年级下册', '沪教版五四制', '8dfe5ae8-b8a1-fc59-86d0-10deab104917', 3),
    ('地理', '七年级上册', '沪教版五四制', 'addfb974-1578-af3f-c180-fde2b2ffc027', 4),
    ('地理', '七年级下册', '沪教版五四制', '961d2539-d72b-dcd5-1312-aa20350cebdf', 4),
    # 补齐：数学六七年级（旧教材，与八九年级同体系）、生物七上（平台仅有新教材版）
    ('数学', '六年级上册', '沪教版五四制', 'df887984-a0ee-45d4-9313-f201934314ca', 5),
    ('数学', '六年级下册', '沪教版五四制', '85a36ac3-3f2a-4804-a2cf-599fa2d201f1', 5),
    ('数学', '七年级上册', '沪教版五四制', 'd96aadda-d47e-4b7b-afb8-d4ee1ee6b999', 5),
    ('数学', '七年级下册', '沪教版五四制', 'de1ffd6e-eddd-4e46-9a6e-59078c9293b5', 5),
    ('生物学', '七年级上册', '沪教版五四制新教材', 'cbfb1a45-26d0-4c6d-84d2-0b38de587160', 5),
]

# 关系键 -> 资料类型（视频类一律跳过）
REL_TYPES = {
    'lesson_plan_design': '教学设计',
    'national_course_resource': None,   # 按 alias_name 细分
    'teaching_assets': None,            # coursewares=课件, 文档 assets 保留
}
VIDEO_TYPES = {'assets_video', 'assets_audio'}

# 子资源 resource_type_code -> 资料类型（新旧教材两种 relations 结构通用）
CODE_MAP = {
    'lesson_plandesign': '教学设计',
    'learning_task': '学习任务单',
    'after_class_exercise': '课后练习',
    'coursewares': '课件',
}

ALIAS_MAP = {'学习任务单': '学习任务单', '课后练习': '课后练习'}


def tree_id_titles(tree_json):
    """树 -> {node_id: title}"""
    out = {}
    def walk(n):
        nid = n.get('id')
        if nid:
            out[nid] = (n.get('title') or '').strip()
        for c in (n.get('child_nodes') or []):
            walk(c)
    if isinstance(tree_json, list):
        for x in tree_json:
            walk(x)
    else:
        walk(tree_json)
    return out


def book_tasks(book):
    """返回 [(下载相对路径, url, 元数据dict)]"""
    subj, grade, ver, bid, prio = book
    tree = get_json_multi(f'/zxx/ndrs/prepare_lesson/trees/{bid}.json')
    if not tree:
        print(f'!! 无章节树 {subj}{grade}')
        return []
    id2title = tree_id_titles(tree)

    parts = get_json_multi(f'/zxx/ndrs/prepare_lesson/teachingmaterials/{bid}/resources/parts.json') or []
    lessons = []
    for purl in parts:
        d = curl_json(purl)
        if d:
            lessons += d
    print(f'== {subj} {grade} {ver}: 课程包 {len(lessons)}')

    tasks, seen = [], set()
    seq_by_ch = {}
    for it in lessons:
        cps = it.get('chapter_paths') or []
        ch_key = cps[0] if cps else '_无章节'
        # 章节目录名：路径各级标题（跳过第一级=全书根）
        ids = cps[0].split('/') if cps else []
        titles = [sanitize(id2title.get(nid, nid)[:40]) for nid in ids]
        ch_dir = '/'.join(titles) if titles else '未分章'
        lesson_title = sanitize(it.get('title') or '未命名课程')
        seq_by_ch[ch_key] = seq_by_ch.get(ch_key, 0) + 1
        seq = seq_by_ch[ch_key]
        rels = it.get('relations') or {}
        picked = {}  # (lesson_id, rtype) -> rel_id，每类取第一个
        for rk, rlist in rels.items():
            for r in (rlist or []):
                cp = r.get('custom_properties') or {}
                if cp.get('prom_resouce_type') in VIDEO_TYPES:
                    continue
                code = r.get('resource_type_code')
                if code in CODE_MAP:
                    rtype = CODE_MAP[code]
                elif rk == 'teaching_assets':
                    alias = ALIAS_MAP.get(cp.get('alias_name') or '')
                    rtype = alias  # 教学资产里的文档
                elif rk == 'national_course_resource':
                    rtype = ALIAS_MAP.get(cp.get('alias_name') or '')
                else:
                    rtype = None
                if not rtype:
                    continue
                key = (it['id'], rtype)
                if key not in picked:
                    picked[key] = r['id']
        for (lesson_id, rtype), rid in picked.items():
            base = os.path.join(OUT_ROOT, sanitize(subj), f'{sanitize(grade)}·{sanitize(ver)}', ch_dir)
            fname = f'{seq:02d}_{lesson_title}_{rtype}.pdf'
            meta = {
                'subject': subj, 'grade': grade, 'version': ver, 'chapter': ch_dir,
                'lesson': it.get('title'), 'rtype': rtype, 'res_id': rid,
                'book_id': bid, 'prio': prio,
                'dest': os.path.join(base, fname),
            }
            tasks.append(meta)
    return tasks


def worker(meta):
    alias, title, pdf = fetch_doc_pdf(meta['res_id'])
    if not pdf:
        meta['status'] = 'nopdf'
        return meta
    meta['url'] = pdf
    meta['status'] = download(pdf, meta['dest'])
    return meta


def main():
    prio_filter = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    books = [b for b in BOOKS if not prio_filter or b[4] <= prio_filter]
    man = open(MANIFEST, 'a', encoding='utf-8')
    for book in books:
        t0 = time.time()
        tasks = book_tasks(book)
        print(f'   待下载文档 {len(tasks)}')
        done = 0
        with ThreadPoolExecutor(6) as ex:
            futs = [ex.submit(worker, m) for m in tasks]
            for f in as_completed(futs):
                m = f.result()
                man.write(json.dumps(m, ensure_ascii=False) + '\n')
                man.flush()
                done += 1
                if done % 20 == 0:
                    print(f'   进度 {done}/{len(tasks)} ({time.time()-t0:.0f}s)')
        print(f'== 完成 {book[0]}{book[1]} 用时 {time.time()-t0:.0f}s')
    man.close()
    print('ALL DONE')


if __name__ == '__main__':
    main()
