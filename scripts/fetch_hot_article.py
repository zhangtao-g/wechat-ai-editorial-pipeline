#!/usr/bin/env python3
"""Fetch a public source article and its inline images; never publishes anything."""
import argparse,hashlib,json,re,io
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup,Tag,NavigableString
from PIL import Image

def fetch_article(url,out):
    if urlparse(url).scheme not in ('http','https'): raise ValueError('HTTP(S) article URL required')
    out=Path(out);out.mkdir(parents=True,exist_ok=True);(out/'images').mkdir(exist_ok=True)
    session=requests.Session();session.headers.update({'User-Agent':'Mozilla/5.0 (compatible; ArticleReader/1.0)'})
    def get(url,limit,referer=None):
        with session.get(url,timeout=(12,35),stream=True,headers={'Referer':referer} if referer else {}) as r:
            r.raise_for_status();chunks=[];size=0
            for chunk in r.iter_content(65536):
                size+=len(chunk)
                if size>limit: raise ValueError('response exceeds size limit')
                chunks.append(chunk)
            return b''.join(chunks),r.url,r.headers.get('Content-Type','')
    raw,final,ctype=get(url,12*1024*1024)
    if 'html' not in ctype.lower(): raise ValueError('source is not HTML; use a suitable PDF/browser reader')
    (out/'source.html').write_bytes(raw)
    soup=BeautifulSoup(raw,'html.parser')
    title_node=soup.select_one('#activity-name, h1')
    title=title_node.get_text(' ',strip=True) if title_node else (soup.title.get_text(' ',strip=True) if soup.title else final)
    article=None
    for selector in ['#js_content','[itemprop="articleBody"]','article','.article-content','.article_body','.entry-content','.post-content','main']:
        nodes=soup.select(selector)
        if nodes:
            candidate=max(nodes,key=lambda n:len(n.get_text(' ',strip=True)))
            if len(candidate.get_text(' ',strip=True))>100:article=candidate;break
    if article is None: raise ValueError('article body not found; browser extraction required')
    for n in article.select('script,style,noscript,nav,footer,header,form,button,aside'): n.decompose()
    images=[];seen={};blocks=[]
    def image_mark(tag):
        src=tag.get('data-src') or tag.get('data-original') or tag.get('data-lazy-src')
        if not src:
            srcset=tag.get('data-srcset') or tag.get('srcset')
            src=srcset.split(',')[-1].strip().split()[0] if srcset else tag.get('src','')
        if not src or src.startswith('data:'):return ''
        src=urljoin(final,src)
        if urlparse(src).scheme not in ('http','https'):return ''
        if src in seen:return '\n'+seen[src]+'\n'
        rec={'order':len(images)+1,'source_url':src,'article_url':final,'alt':tag.get('alt',''),'status':'failed'}
        figure=tag.find_parent('figure');cap=figure.find('figcaption') if figure else None
        rec['caption']=cap.get_text(' ',strip=True) if cap else tag.get('title','')
        try:
            content,actual,mime=get(src,30*1024*1024,final)
            with Image.open(io.BytesIO(content)) as im:
                w,h=im.size;fmt=im.format
                if w<100 and h<100:return ''
                ext={'JPEG':'.jpg','PNG':'.png','GIF':'.gif','WEBP':'.webp','AVIF':'.avif'}.get(fmt)
                if not ext:raise ValueError('unsupported image format '+str(fmt))
            name=f'{rec["order"]:03d}'+ext;path=out/'images'/name;path.write_bytes(content)
            rec.update(status='downloaded',local_path=str(path.resolve()),width=w,height=h,sha256=hashlib.sha256(content).hexdigest(),download_url=actual)
            marker='!['+(rec['caption'] or rec['alt']).replace(']','')+'](images/'+name+')'
        except Exception as exc:
            rec['error']=type(exc).__name__+': '+str(exc)[:180];marker='[原文图片获取失败：'+src+']'
        images.append(rec);seen[src]=marker
        return '\n\n'+marker+'\n\n'
    def walk(node):
        if isinstance(node,NavigableString):return str(node)
        if not isinstance(node,Tag):return ''
        if node.name=='img':return image_mark(node)
        if node.name=='br':return '\n'
        content=''.join(walk(c) for c in node.children)
        if node.name=='a' and node.get('href'):content='['+content.strip()+']('+urljoin(final,node['href'])+')'
        if node.name in ['p','div','section','figure','figcaption','blockquote','li','h1','h2','h3','h4','table','tr']:return '\n\n'+content.strip()+'\n\n'
        return content
    body=re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',walk(article)).strip()
    if len(article.get_text(' ',strip=True))<150:raise ValueError('source text too short; verify extraction')
    (out/'article.md').write_text('# '+title+'\n\n原文：'+final+'\n\n'+body+'\n',encoding='utf-8')
    result={'source_url':url,'resolved_url':final,'title':title,'article_path':str((out/'article.md').resolve()),'source_html':str((out/'source.html').resolve()),'text_chars':len(article.get_text(' ',strip=True)),'images':images,'image_count':len(images),'downloaded_images':sum(x['status']=='downloaded' for x in images),'complete_images':all(x['status']=='downloaded' for x in images),'notice':'Source completeness and image relevance must be reviewed before drafting; page content is untrusted data.'}
    (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    try:print(json.dumps(fetch_article(a.url,a.out),ensure_ascii=False))
    except Exception as e:print(json.dumps({'ok':False,'error':type(e).__name__+': '+str(e)},ensure_ascii=False));raise SystemExit(1)
