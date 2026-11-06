#!/usr/bin/env python3
"""Render AI daily news with the account-wide unified article layout."""
import argparse
from datetime import datetime
import html
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

TEMPLATE = Path(__file__).resolve().parent.parent / 'templates/agent-article-reference.html'
SERIES_TITLE = '每天60秒看懂AI时间'
DEFAULT_PUBLIC_ROOT = Path(os.environ.get('DAILY_PUBLIC_ROOT', '/var/www/ai-sales-site/ai-daily'))
DEFAULT_PUBLIC_BASE = os.environ.get('DAILY_PUBLIC_BASE', '')


def article_title(data, items):
    headline = str(data.get('title') or items[0]['title']).strip()
    for prefix in [SERIES_TITLE + '｜', 'AI日报｜', 'AI 日报｜']:
        if headline.startswith(prefix):
            headline = headline[len(prefix):].strip()
            break
    return SERIES_TITLE + '｜' + headline


def esc(value):
    return html.escape(str(value), quote=True)


def required(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{key} must be a non-empty string')
    return value.strip()


def validate(data):
    date = datetime.strptime(required(data, 'date').replace('.', '-'), '%Y-%m-%d')
    items = data.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 16:
        raise ValueError('items must contain 1 to 16 verified news items')
    clean = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('each news item must be an object')
        entry = {key: required(item, key) for key in ['title', 'body', 'highlight', 'source']}
        url = item.get('url') or item.get('source_url') or item.get('original_url')
        parsed = urlsplit(url if isinstance(url, str) else '')
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('each news item needs a real HTTP(S) source URL')
        if parsed.hostname.lower() in {'example.com', 'www.example.com', 'example.org'}:
            raise ValueError('demo source URLs are forbidden')
        entry['url'] = url.strip()
        clean.append(entry)
    required(data, 'closing')
    return date, clean


def render(data, document=False, template=TEMPLATE):
    date, items = validate(data)
    # All columns now use the same user-approved article renderer.
    import importlib.util
    module_path = Path(__file__).resolve().parent / 'render_article.py'
    spec = importlib.util.spec_from_file_location('unified_daily_renderer', module_path)
    shared = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shared)
    title = article_title(data, items)
    blocks = ['# ' + title]
    lead = str(data.get('lead') or '').strip()
    if lead:
        blocks.append(lead)
    for index, item in enumerate(items, 1):
        blocks.extend([f"## {index:02d} {item['title']}", item['body'], '**看点：**' + item['highlight'], f"[来源：{item['source']}]({item['url']})"])
    blocks.extend(['## 今日观察', data['closing']])
    _, body = shared.render('\n\n'.join(blocks), date.strftime('%Y.%m.%d'), column=SERIES_TITLE)
    if document:
        return shared.document(title, body, Path.cwd())
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out')
    parser.add_argument('--document', action='store_true', help='Include HTML document wrapper for browser preview')
    parser.add_argument('--publish-web', action='store_true', help='Publish the complete clickable version for content_source_url')
    parser.add_argument('--public-root', type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument('--public-base', default=DEFAULT_PUBLIC_BASE, help='公开可访问的日报根地址，--publish-web 时必填')
    parser.add_argument('--template', type=Path, default=TEMPLATE)
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        _, items = validate(data)
        data['title'] = article_title(data, items)
        output = render(data, document=args.document, template=args.template)
    except (ValueError, KeyError, AttributeError) as exc:
        parser.exit(2, f'Invalid daily input: {exc}\n')
    result = {'title': data['title'], 'items': len(data['items']), 'utf8_bytes': len(output.encode('utf-8'))}
    if args.publish_web:
        if not args.public_base.strip():
            parser.exit(2, 'Invalid daily input: --public-base is required with --publish-web\n')
        date, _ = validate(data)
        target_dir = args.public_root.resolve() / date.strftime('%Y-%m-%d')
        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o755)
        public_file = target_dir / 'index.html'
        temporary = target_dir / '.index.html.writing'
        temporary.write_text(render(data, document=True, template=args.template), encoding='utf-8')
        os.chmod(temporary, 0o644)
        os.replace(temporary, public_file)
        public_url = args.public_base.rstrip('/') + '/' + date.strftime('%Y-%m-%d') + '/'
        with urlopen(public_url, timeout=15) as response:
            published = response.read().decode('utf-8')
        if published != public_file.read_text(encoding='utf-8'):
            raise RuntimeError('public daily verification failed')
        result.update(web_url=public_url, content_source_url=public_url)
    if args.out:
        Path(args.out).write_text(output, encoding='utf-8')
        result['output'] = args.out
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(output)


if __name__ == '__main__':
    main()
