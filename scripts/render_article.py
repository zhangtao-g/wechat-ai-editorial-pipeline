"""Agent实验室热点公众号模板：中文正文、原图、中文图注、可追溯来源。"""
import argparse, base64, html, mimetypes, re
from pathlib import Path

def inline(text):
    text=html.escape(text)
    text=re.sub(r'\*\*(.+?)\*\*',r'<strong style="color:#059669;font-weight:700;">\1</strong>',text)
    text=re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',r'<a href="\2" style="color:#059669;text-decoration:none;">\1</a><span style="display:block;font-size:12px;color:#888;overflow-wrap:anywhere;">原文网址：\2</span>',text)
    return text

def render(markdown,date='2026.10.19',author='Agent实验室',column='AI热点'):
    lines=markdown.strip().splitlines()
    title=lines.pop(0).removeprefix('# ').strip()
    parts=[]
    for block in '\n'.join(lines).split('\n\n'):
        block=block.strip()
        if not block:continue
        image=re.fullmatch(r'!\[(.*?)\]\((.*?)\)',block,re.S)
        if image:
            parts.append('<p style="margin:24px 0 12px;"><img alt="'+html.escape(image[1],quote=True)+'" src="'+html.escape(image[2],quote=True)+'" style="width:100%;max-width:100%;height:auto;display:block;" /></p>')
        elif block.startswith('## '):
            parts.append('<h2 style="font-size:20px;line-height:1.5;font-weight:700;border-left:4px solid #059669;padding:2px 0 2px 12px;margin:32px 0 18px;">'+inline(block[3:])+'</h2>')
        elif block=='---':parts.append('<section style="border-top:1px solid #ddd;margin:30px 0;"></section>')
        elif re.match(r'^图\d+\s*[｜|]',block):
            parts.append('<p style="font-size:13px;line-height:1.8;color:#777;margin:8px 0 24px;">'+inline(block)+'</p>')
        else:parts.append('<p style="font-size:16px;line-height:1.9;margin:16px 0;">'+inline(block).replace('\n','<br />')+'</p>')
    header='<section style="border-bottom:1px solid #a7d9c8;padding-bottom:22px;margin-bottom:24px;"><p style="color:#059669;font-size:13px;letter-spacing:2px;margin:0;">'+html.escape(author)+' · '+html.escape(column)+'</p><p style="font-size:13px;color:#888;margin:0;">'+html.escape(date)+' · 公开资料整理与分析</p></section>'
    return title,'<section style="font-family:system-ui,-apple-system,Microsoft YaHei,sans-serif;font-size:16px;line-height:1.9;letter-spacing:.3px;overflow-wrap:anywhere;">'+header+''.join(parts)+'</section>'

def document(title,body,root):
    def embed(match):
        src=html.unescape(match[1])
        if src.startswith(('http:','https:','data:')):return match[0]
        p=(root/src).resolve()
        if not p.is_file():raise FileNotFoundError(p)
        mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        return 'src="data:'+mime+';base64,'+base64.b64encode(p.read_bytes()).decode()+'"'
    body=re.sub(r'src="([^\"]+)"',embed,body)
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>body{margin:0;background:#f2f5f3;color:#333}main{max-width:680px;margin:24px auto;padding:28px;background:#fff;overflow-wrap:anywhere}img{max-width:100%;height:auto}@media(max-width:600px){body{background:white}main{margin:0;padding:20px}}</style><main>'+body+'</main></html>'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--out',required=True);p.add_argument('--preview');p.add_argument('--date',required=True);p.add_argument('--author',default='Agent实验室');p.add_argument('--column',default='AI热点');a=p.parse_args()
    source=Path(a.input);title,body=render(source.read_text(encoding='utf-8'),a.date,a.author,a.column)
    Path(a.out).write_text(body,encoding='utf-8')
    if a.preview:Path(a.preview).write_text(document(title,body,source.parent),encoding='utf-8')
