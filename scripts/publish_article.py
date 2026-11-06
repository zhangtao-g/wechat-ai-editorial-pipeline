#!/usr/bin/env python3
"""publish_article.py — 公众号文章后段流水线一条命令跑完。

渲染 → 封面 → 上传正文图/封面 → 组装 payload → wechat_duplicate_guard 建稿
→ draft/get 回查 → mark_written → notify_draft。

用法：
  python3 publish_article.py --md /path/art.md --column 周总结 --date 2026.11.01 \
    --digest '摘要' --cover-title 'AI 的账单<br><em>摊开了</em>' \
    --cover-sub '副标题' --cover-kicker '周总结 · 1101' \
    --source-url 'https://原文地址' [--dry-run] [--skip-notify]

--dry-run 只跑到「payload 已生成」，不建草稿、不记账、不通知。
退出码非 0 表示失败，stdout 最后一行是 JSON 摘要。
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import requests

from wechat_credentials import access_token

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
GUARD = SCRIPTS / 'wechat_duplicate_guard.py'
RENDER = SCRIPTS / 'render_article.py'
MAKE_COVER = REPO / 'covers/make_cover.py'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def hanzi(text):
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit('command failed: %s\n%s\n%s' % (' '.join(map(str, cmd)),
                                                         r.stdout[-800:], r.stderr[-800:]))
    return r.stdout


def uploadimg(tok, path):
    before = sha(path)
    mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
    with open(path, 'rb') as f:
        r = requests.post('https://api.weixin.qq.com/cgi-bin/media/uploadimg',
                          params={'access_token': tok},
                          files={'media': (path.name, f, mime)}, timeout=60)
    d = json.loads(r.content.decode('utf-8'))
    assert before == sha(path), 'local image changed during upload: %s' % path
    if 'url' not in d:
        raise SystemExit('uploadimg failed %s: %s' % (path.name, d))
    return {'file': str(path), 'sha256': before, 'url': d['url']}


def upload_cover(tok, path):
    before = sha(path)
    with open(path, 'rb') as f:
        r = requests.post('https://api.weixin.qq.com/cgi-bin/material/add_material',
                          params={'access_token': tok, 'type': 'image'},
                          files={'media': ('cover.png', f, 'image/png')}, timeout=60)
    d = json.loads(r.content.decode('utf-8'))
    assert before == sha(path), 'cover changed during upload'
    if 'media_id' not in d:
        raise SystemExit('cover upload failed: %s' % d)
    return {'media_id': d['media_id'], 'url': d.get('url', ''), 'sha256': before}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--md', required=True)
    ap.add_argument('--column', required=True)
    ap.add_argument('--date', required=True, help='YYYY.MM.DD')
    ap.add_argument('--digest', required=True)
    ap.add_argument('--cover-title', required=True, help='支持 <br> 和 <em>')
    ap.add_argument('--cover-sub', default='')
    ap.add_argument('--cover-kicker', default='')
    ap.add_argument('--cover-accent', default='#00FF9D')
    ap.add_argument('--source-url', default='')
    ap.add_argument('--author', default='Agent实验室')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--skip-notify', action='store_true')
    a = ap.parse_args()

    md = Path(a.md).resolve()
    if not md.exists():
        raise SystemExit('md not found: %s' % md)
    stem = md.stem
    outdir = md.parent
    body_path = outdir / (stem + '-body.html')
    preview_path = outdir / (stem + '-preview.html')
    wechat_body_path = outdir / (stem + '-wechat-body.html')
    payload_path = outdir / (stem + '-payload.json')
    map_path = outdir / (stem + '-image-map.json')
    verify_path = outdir / (stem + '-verify.json')
    cover_path = outdir / (stem + '-cover.png')

    raw = md.read_text(encoding='utf-8')
    lines = raw.splitlines()
    title = lines[0].lstrip('#').strip()
    if not title:
        raise SystemExit('first line must be "# 标题"')
    body_text = '\n'.join(lines[1:])
    chars = hanzi(body_text.split('资料来源：')[0])
    digest_bytes = len(a.digest.encode('utf-8'))
    if digest_bytes > 70:
        raise SystemExit('digest %d bytes > 70' % digest_bytes)

    # 1 渲染
    run([sys.executable, str(RENDER), '--input', str(md), '--out', str(body_path),
         '--preview', str(preview_path), '--date', a.date, '--column', a.column])
    body = body_path.read_text(encoding='utf-8')
    imgs_found = re.findall(r'src="(images/[^"]+)"', body)
    caps = len(re.findall(r'图\d+｜', body))
    if len(imgs_found) != caps:
        raise SystemExit('img/caption mismatch: %d imgs vs %d captions' % (len(imgs_found), caps))
    if title in body:
        raise SystemExit('title leaked into body')

    # 2 封面
    run([sys.executable, str(MAKE_COVER), '--title', a.cover_title, '--sub', a.cover_sub,
         '--kicker', a.cover_kicker, '--accent', a.cover_accent, '--out', str(cover_path)])
    from PIL import Image
    w, h = Image.open(cover_path).size
    if (w, h) != (1880, 800):
        raise SystemExit('cover size %dx%d, expected 1880x800' % (w, h))

    # 3 上传正文图（可复用 map 里的地址）
    tok = access_token()
    cached = json.loads(map_path.read_text(encoding='utf-8')) if map_path.exists() else {}
    by_rel = {i['rel']: i for i in cached.get('images', [])}
    images = []
    for rel in imgs_found:
        p = outdir / rel
        if rel in by_rel and sha(p) == by_rel[rel].get('sha256'):
            up = by_rel[rel]
        else:
            up = {'rel': rel, **uploadimg(tok, p)}
        images.append(up)
        body = body.replace('src="%s"' % rel, 'src="%s"' % up['url'])
    if 'src="images/' in body:
        raise SystemExit('relative image path left in body')
    if str(Path.home()) in body:
        raise SystemExit('absolute local path left in body')

    # 4 封面
    if cached.get('cover', {}).get('sha256') == sha(cover_path) and cached['cover'].get('media_id'):
        cover = cached['cover']
    else:
        cover = upload_cover(tok, cover_path)

    # 5 payload
    payload = {'articles': [{
        'title': title,
        'author': a.author,
        'digest': a.digest,
        'content': body,
        'content_source_url': a.source_url,
        'thumb_media_id': cover['media_id'],
        'need_open_comment': 1,
        'only_fans_can_comment': 0,
    }]}
    wechat_body_path.write_text(body, encoding='utf-8')
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    map_path.write_text(json.dumps({'cover': cover, 'images': images},
                                   ensure_ascii=False, indent=1), encoding='utf-8')

    summary = {'title': title, 'chars': chars, 'digest_bytes': digest_bytes,
               'imgs': len(images), 'h2': body.count('<h2'),
               'payload': str(payload_path), 'cover': str(cover_path)}
    if a.dry_run:
        summary['dry_run'] = True
        print(json.dumps(summary, ensure_ascii=False))
        return

    # 6 建稿（统一入口，含查重锁）
    out = run([sys.executable, str(GUARD), '--payload', str(payload_path)])
    mid = json.loads(out.strip().splitlines()[-1]).get('media_id')
    if not mid:
        raise SystemExit('no media_id from guard: %s' % out[-500:])
    summary['media_id'] = mid

    # 7 回查
    r = requests.post('https://api.weixin.qq.com/cgi-bin/draft/get',
                      params={'access_token': tok},
                      data=json.dumps({'media_id': mid}).encode('utf-8'),
                      headers={'Content-Type': 'application/json; charset=utf-8'}, timeout=30)
    r.encoding = 'utf-8'
    ni = r.json()['news_item'][0]
    content = ni['content']
    sigs = [u.split('//')[1].split('/')[2]
            for u in re.findall(r'src="(https?://mmbiz[^"]+)"', content)]
    want = [u.split('//')[1].split('/')[2] for u in re.findall(r'src="(https?://mmbiz[^"]+)"', body)]
    checks = {
        'title': ni['title'] == title,
        'digest': ni.get('digest') == a.digest,
        'imgs': content.count('<img') == len(images),
        'img_sigs': sigs == want,
        'thumb': ni.get('thumb_media_id') == cover['media_id'],
        'no_local_path': 'images/' not in content and str(Path.home()) not in content,
    }
    verify_path.write_text(json.dumps({'media_id': mid, **checks, 'content_len': len(content)},
                                      ensure_ascii=False, indent=1), encoding='utf-8')
    summary['checks'] = checks
    if not all(checks.values()):
        raise SystemExit('verify failed: %s' % json.dumps(checks, ensure_ascii=False))

    # 8 记账 + 通知
    run([sys.executable, str(SCRIPTS / 'mark_written.py'), '--title', title,
         '--channel', a.column, '--media-id', mid])
    if not a.skip_notify:
        n = run([sys.executable, str(SCRIPTS / 'notify_draft.py'), '--title', title,
                 '--channel', a.column, '--media-id', mid, '--chars', str(chars)])
        summary['notify'] = json.loads(n.strip().splitlines()[-1])
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
