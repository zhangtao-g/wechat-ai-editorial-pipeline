#!/usr/bin/env python3
"""Commit verified drafts to both the shared event ledger and legacy receipts."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys

from ai_news import db,commit,resolve

HERMES_HOME=Path(os.environ.get('HERMES_HOME', str(Path.home()/'.hermes')))

p=argparse.ArgumentParser();p.add_argument('--uuid',default='');p.add_argument('--event-ids',default='');p.add_argument('--items-file');p.add_argument('--title',required=True);p.add_argument('--rank',type=int,default=0);p.add_argument('--media-id',required=True);p.add_argument('--channel',default='发布位');p.add_argument('--daily',action='store_true');a=p.parse_args()
mode='daily' if a.daily else 'hot'
keys=[k for k in (a.event_ids or a.uuid).split(',') if k]
with db() as c:
    # Weekly and unrelated columns keep their legacy receipt behavior.
    if a.daily or keys:
        ids=commit(c,mode,a.media_id,a.items_file,keys)
    else:ids=[]
    b=HERMES_HOME/'workspace/history';b.mkdir(parents=True,exist_ok=True)
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    rec={'date':now.date().isoformat(),'at':now.isoformat(timespec='seconds'),'uuid':a.uuid,'event_ids':ids,'title':a.title,'rank':a.rank,'media_id':a.media_id,'channel':a.channel,'items_file':a.items_file}
    target=b/('daily_written.jsonl' if a.daily else 'written.jsonl')
    # Single receipt per draft; rerunning notification does not consume quota again.
    old=[json.loads(x) for x in target.read_text(encoding='utf-8').splitlines() if x.strip()] if target.exists() else []
    if not any(x.get('media_id')==a.media_id for x in old):
        with target.open('a',encoding='utf-8') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
print(json.dumps({'ok':True,'event_ids':ids,'media_id':a.media_id},ensure_ascii=False))
