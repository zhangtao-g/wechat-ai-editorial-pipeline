#!/usr/bin/env python3
"""Last-mile duplicate barrier for WeChat drafts. Never logs credentials."""
import contextlib
import fcntl
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qs, urlsplit

HOME = Path(os.environ.get('HERMES_HOME', str(Path.home()/'.hermes')))
ROOT = HOME/'news'
_installed = False

def text(value):
    return re.sub(r'\s+', '', html.unescape(re.sub(r'<[^>]*>', '', value or ''))).casefold()

def shingles(value):
    value = text(value)
    return {value[i:i+12] for i in range(max(0, len(value)-11))}

def channel(row, mapping=None):
    ident=str(row.get('id') or row.get('media_id') or '').split(':')[0]
    if mapping and ident in mapping:return mapping[ident]
    explicit=row.get('_channel') or row.get('channel')
    if explicit in ('daily','hot'):return explicit
    title=row.get('title','')
    return 'daily' if re.match(r'^(?:每天60秒看懂AI时间|AI日报|AI日報)',title,re.I) else 'hot'

def comparison(candidate, previous, mapping=None):
    import ai_news
    cross={channel(candidate,mapping),channel(previous,mapping)}=={'daily','hot'}
    a, b = candidate.get('title',''), previous.get('title','')
    if not cross and a and b and ai_news.norm(a) == ai_news.norm(b): return 'same_title'
    if not cross and a and b and ai_news.same_event(a,b): return 'same_event_title'
    ua = ai_news.canonical(candidate.get('content_source_url') or candidate.get('url') or '')
    ub = ai_news.canonical(previous.get('content_source_url') or previous.get('url') or '')
    if not cross and ua and ua == ub and len(urlsplit(ua).path.strip('/')) > 5: return 'same_original_article'
    aa,bb = shingles(candidate.get('content') or candidate.get('body','')), shingles(previous.get('content') or previous.get('body',''))
    denominator=max(len(aa),len(bb)) if cross else min(len(aa),len(bb))
    if min(len(aa),len(bb)) >= 150 and len(aa&bb)/denominator >= (.9 if cross else .65):
        return 'same_body_despite_title_change'
    return ''

def connect():
    ROOT.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(ROOT/'wechat-archive.sqlite3',timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS archive(id TEXT PRIMARY KEY,title TEXT,content TEXT,content_source_url TEXT,origin TEXT,at REAL)')
    if 'channel' not in {r[1] for r in c.execute('PRAGMA table_info(archive)')}:c.execute('ALTER TABLE archive ADD COLUMN channel TEXT')
    return c

def archive(rows, origin):
    with connect() as c:
        for i,row in enumerate(rows):
            ident=row.get('id') or row.get('media_id') or row.get('article_id')
            if not ident:continue
            c.execute('INSERT OR REPLACE INTO archive VALUES(?,?,?,?,?,?,?)',
                      (str(ident)+':'+str(row.get('index',i)),row.get('title',''),row.get('content') or row.get('body',''),row.get('content_source_url') or row.get('url',''),origin,time.time(),channel(row)))

def flatten(rows):
    out=[]
    for row in rows:
        for i,a in enumerate(row.get('content',{}).get('news_item',[])):
            out.append(dict(a,id=row.get('media_id') or row.get('article_id'),index=i))
    return out

def batch(session, token, name):
    rows=[];offset=0
    while True:
        r=session.post('https://api.weixin.qq.com/cgi-bin/'+name+'/batchget',params={'access_token':token},json={'offset':offset,'count':20,'no_content':0},timeout=35)
        if r.status_code != 200:raise RuntimeError('History check HTTP '+str(r.status_code))
        d=json.loads(r.content.decode('utf-8'))
        if d.get('errcode'):
            if name=='freepublish' and d['errcode']==48001:return [],'permission_denied_48001'
            raise RuntimeError('History check failed: '+str(d['errcode']))
        items=d.get('item',[]);rows.extend(items);offset+=len(items)
        if not items or offset>=d.get('total_count',0):return flatten(rows),'ok'

def local_history():
    import ai_news
    rows=[]
    for name in ['written.jsonl','daily_written.jsonl']:
        p=HOME/'workspace/history'/name
        if not p.exists():continue
        for line in p.read_text(encoding='utf-8').splitlines():
            try:r=json.loads(line)
            except ValueError:continue
            if not r.get('media_id'):continue
            mode='daily' if name=='daily_written.jsonl' else 'hot'
            rows.append(dict(r,id=r['media_id'],_channel=mode))
            p=Path(r.get('items_file') or '/nonexistent')
            if p.is_file():
                d=json.loads(p.read_text(encoding='utf-8'))
                for i,x in enumerate(d.get('items') or [d]):rows.append(dict(x,id=r['media_id'],index=i+100,_channel=mode))
    if (ROOT/'events.sqlite3').exists():
        with ai_news.db() as c:
            for r in c.execute('SELECT DISTINCT d.media_id,d.channel,e.title,a.url FROM delivered d JOIN events e ON d.event_id=e.id LEFT JOIN articles a ON a.event_id=e.id'):
                rows.append(dict(r,id=r['media_id']))
    return rows

def check(articles, session, token, exclude_id=None):
    # Live reads are mandatory; an outage must not silently permit an upload.
    drafts,ds=batch(session,token,'draft')
    published,ps=batch(session,token,'freepublish')
    archive(drafts,'live_draft');archive(published,'published')
    local=local_history()
    mapping={r.get('id'):channel(r) for r in local if r.get('id')}
    with connect() as c:older=[dict(r) for r in c.execute('SELECT * FROM archive')]
    previous=drafts+published+local+older
    matches=[]
    for i,a in enumerate(articles):
        for b in previous:
            ident=str(b.get('id') or b.get('media_id') or '')
            if exclude_id and (ident==exclude_id or ident.startswith(exclude_id+':')):continue
            reason=comparison(a,b,mapping)
            if reason:
                matches.append({'index':i,'reason':reason,'previous_title':b.get('title'),'previous_id':ident})
                break
        for b in articles[:i]:
            reason=comparison(a,b,mapping)
            if reason:matches.append({'index':i,'reason':'within_upload_'+reason})
    report={'ok':not matches,'drafts_checked':len(drafts),'published_checked':len(published),'published_api':ps,'local_records':len(local),'matches':matches,'at':time.time()}
    p=ROOT/'health/last-upload-duplicate-check.json';p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');p.chmod(0o600)
    if matches:raise ValueError('Duplicate article blocked: '+json.dumps(matches,ensure_ascii=False))
    return report

def install():
    """Protect requests-based legacy uploaders too, independent of prompt compliance."""
    global _installed
    if _installed:return
    import requests
    original=requests.sessions.Session.request
    def guarded(session,method,url,**kw):
        p=urlsplit(url)
        if p.hostname!='api.weixin.qq.com' or p.path not in ('/cgi-bin/draft/add','/cgi-bin/freepublish/submit'):
            return original(session,method,url,**kw)
        if p.path.endswith('/submit'):
            raise ValueError('Automatic publication disabled; use the reviewed draft workflow')
        body=kw.get('json')
        if body is None:
            raw=kw.get('data') or '{}'
            body=json.loads(raw.decode('utf-8') if isinstance(raw,bytes) else raw)
        token=(kw.get('params') or {}).get('access_token') or parse_qs(p.query).get('access_token',[''])[0]
        if not token:raise ValueError('Cannot run duplicate check without an access token')
        articles=body.get('articles',[])
        if not articles:raise ValueError('No article to validate')
        ROOT.mkdir(parents=True,exist_ok=True)
        with (ROOT/'.wechat-upload.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            check(articles,session,token)
            response=original(session,method,url,**kw)
            result=json.loads(response.content.decode('utf-8'))
            if result.get('media_id'):
                archive([dict(a,id=result['media_id'],index=i) for i,a in enumerate(articles)],'created_draft')
            return response
    requests.sessions.Session.request=guarded
    _installed=True

def main():
    import argparse, requests
    from wechat_credentials import access_token
    parser=argparse.ArgumentParser();parser.add_argument('--payload',required=True);parser.add_argument('--audit-existing',action='store_true')
    args=parser.parse_args()
    s=requests.Session()
    token=access_token()
    payload=json.loads(Path(args.payload).read_text(encoding='utf-8'))
    articles=payload.get('articles') or [payload]
    if args.audit_existing:
        print(json.dumps(check(articles,s,token,exclude_id=payload.get('media_id')),ensure_ascii=False));return
    install()
    r=s.post('https://api.weixin.qq.com/cgi-bin/draft/add',params={'access_token':token},data=json.dumps({'articles':articles},ensure_ascii=False).encode('utf-8'),headers={'Content-Type':'application/json; charset=utf-8'},timeout=90)
    d=json.loads(r.content.decode('utf-8'))
    if not d.get('media_id'):raise RuntimeError('Draft API error '+str(d.get('errcode')))
    print(json.dumps(d,ensure_ascii=False))

if __name__=='__main__':main()
