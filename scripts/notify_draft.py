#!/usr/bin/env python3
"""Durable Feishu notifications for completed WeChat drafts (stdlib only)."""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

HOME = Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes')))
HISTORY = HOME / 'workspace/history'
CONFIG = HOME / 'notification_config.json'
CST = timezone(timedelta(hours=8))


def records(path):
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj
            except json.JSONDecodeError:
                continue


def database():
    HISTORY.mkdir(parents=True, exist_ok=True)
    path = HISTORY / 'draft_notifications.sqlite3'
    db = sqlite3.connect(path, timeout=20)
    os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS notifications (
            media_id TEXT PRIMARY KEY, title TEXT NOT NULL, channel TEXT NOT NULL,
            chars INTEGER NOT NULL DEFAULT 0, rank INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_at REAL NOT NULL DEFAULT 0, last_error TEXT,
            created_at TEXT NOT NULL, sent_at TEXT);
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
    ''')
    return db


def enqueue(db, rec, baseline=False):
    mid, title = str(rec.get('media_id') or '').strip(), str(rec.get('title') or '').strip()
    if not mid or not title:
        return False
    db.execute('''INSERT OR IGNORE INTO notifications
        (media_id,title,channel,chars,rank,status,created_at) VALUES (?,?,?,?,?,?,?)''',
        (mid, title, str(rec.get('channel') or '发布位'), int(rec.get('chars') or 0),
         int(rec.get('rank') or 0), 'baseline' if baseline else 'pending',
         datetime.now(CST).isoformat(timespec='seconds')))
    db.commit()
    return True


def sync_history(db):
    # First boot: preserve previously successful notifications, import failed ones.
    first = db.execute("SELECT value FROM metadata WHERE key='initialized'").fetchone() is None
    pending = list(records(HISTORY / 'pending_notifications.jsonl')) if first else []
    for rec in pending:
        enqueue(db, rec)
    for name in ['written.jsonl', 'daily_written.jsonl']:
        for rec in records(HISTORY / name):
            enqueue(db, rec, baseline=first)
    if first:
        db.execute("INSERT INTO metadata VALUES ('initialized',?)", (str(time.time()),))
        db.commit()


def load_config():
    if not CONFIG.exists():
        return None
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    url = str(cfg.get('webhook_url') or '')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'open.feishu.cn', 'open.larksuite.com'} or not parsed.path.startswith('/open-apis/bot/v2/hook/'):
        raise ValueError('invalid_feishu_webhook')
    return cfg


def message(rec, keyword='公众号草稿'):
    meta = [rec['channel']]
    if rec['chars']:
        meta.append(f"{rec['chars']}字")
    if rec['rank']:
        meta.append(f"热点第{rec['rank']}名")
    return '\n'.join([
        f'{keyword}提醒：已进入公众号草稿箱，请手动发布。',
        f"《{rec['title']}》", ' · '.join(meta),
        f"草稿ID：{rec['media_id']}", '请在公众号后台核对正文并声明原创后发布。'])


def payload(text, secret='', timestamp=None):
    data = {'msg_type': 'text', 'content': {'text': text}}
    if secret:
        stamp = str(int(time.time()) if timestamp is None else timestamp)
        key = f'{stamp}\n{secret}'.encode('utf-8')
        data.update(timestamp=stamp, sign=base64.b64encode(hmac.new(key, b'', hashlib.sha256).digest()).decode())
    return data


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_feishu(cfg, text):
    body = json.dumps(payload(text, cfg.get('signing_secret', '')), ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(cfg['webhook_url'], data=body, headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        return False, f'feishu_http_{exc.code}'
    except Exception as exc:
        # Do not log exception text: network errors can contain the secret webhook.
        return False, f'feishu_transport_{type(exc).__name__}'
    if not isinstance(result, dict):
        return False, 'feishu_invalid_response'
    code = result.get('code', result.get('StatusCode'))
    if type(code) is int and code == 0:
        return True, None
    return False, 'feishu_api_' + str(code) if type(code) is int else 'feishu_missing_code'


@contextmanager
def delivery_lock():
    HISTORY.mkdir(parents=True, exist_ok=True)
    with (HISTORY / '.draft_notifications.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def drain(db, sender=send_feishu, clock=time.time, only=None):
    cfg = load_config()
    if cfg is None:
        return {'sent': 0, 'pending': count(db, 'pending'), 'reason': 'feishu_not_configured'}
    sql = "SELECT * FROM notifications WHERE status='pending' AND next_at<=?"
    params = [clock()]
    if only:
        sql += ' AND media_id=?'
        params.append(only)
    rows = db.execute(sql + ' ORDER BY created_at LIMIT 10', params).fetchall()
    sent = 0
    for rec in rows:
        ok, error = sender(cfg, message(rec, cfg.get('keyword') or '公众号草稿'))
        if ok:
            db.execute("UPDATE notifications SET status='sent',sent_at=?,attempts=attempts+1,last_error=NULL WHERE media_id=?",
                       (datetime.now(CST).isoformat(timespec='seconds'), rec['media_id']))
            sent += 1
        else:
            # Retry forever, with bounded exponential backoff (1,2,4,8,15 min).
            delay = min(900, 60 * 2 ** min(rec['attempts'], 4))
            db.execute('UPDATE notifications SET attempts=attempts+1,next_at=?,last_error=? WHERE media_id=?',
                       (clock() + delay, error, rec['media_id']))
        db.commit()
    return {'sent': sent, 'pending': count(db, 'pending')}


def count(db, status):
    return db.execute('SELECT count(*) FROM notifications WHERE status=?', (status,)).fetchone()[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--title')
    parser.add_argument('--channel', default='发布位')
    parser.add_argument('--media-id', default='')
    parser.add_argument('--chars', type=int, default=0)
    parser.add_argument('--rank', type=int, default=0)
    parser.add_argument('--drain', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    if not args.status and not args.drain and (not args.title or not args.media_id):
        parser.error('--title and --media-id are required')
    with delivery_lock():
        db = database()
        sync_history(db)
        if args.status:
            print(json.dumps({'configured': CONFIG.exists(), 'pending': count(db, 'pending'),
                              'sent': count(db, 'sent'), 'baseline': count(db, 'baseline')}, ensure_ascii=False))
            return 0
        if args.title:
            enqueue(db, vars(args))
        try:
            result = drain(db, only=args.media_id if args.title else None)
        except (ValueError, json.JSONDecodeError):
            result = {'sent': 0, 'pending': count(db, 'pending'), 'reason': 'invalid_feishu_config'}
        if args.title:
            row = db.execute('SELECT status FROM notifications WHERE media_id=?', (args.media_id,)).fetchone()
            result.update(delivered=row['status'] in {'sent', 'baseline'}, queued=row['status'] == 'pending')
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('delivered', result['pending'] == 0) else 1


if __name__ == '__main__':
    raise SystemExit(main())
