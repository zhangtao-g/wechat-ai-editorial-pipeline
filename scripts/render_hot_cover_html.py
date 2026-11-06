#!/usr/bin/env python3
"""Render independently designed cover HTML, without imposing any visual template."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

p=argparse.ArgumentParser();p.add_argument('--html',required=True);p.add_argument('--out',required=True);a=p.parse_args()
source=Path(a.html).resolve(strict=True);out=Path(a.out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
module_path=Path(__file__).resolve().parent.parent/'covers/make_cover.py'
spec=importlib.util.spec_from_file_location('existing_chrome_locator',module_path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
chrome=m.find_chrome()
if not chrome:raise SystemExit('Chromium unavailable')
r=subprocess.run([chrome,'--headless','--disable-gpu','--hide-scrollbars','--no-sandbox','--force-device-scale-factor=2','--window-size=940,400','--screenshot='+str(out),source.as_uri()],capture_output=True,timeout=90)
if r.returncode or not out.exists():raise SystemExit('Cover render failed; inspect HTML and Chromium availability')
from PIL import Image
with Image.open(out) as im:
    if im.size!=(1880,800):raise SystemExit('Unexpected cover dimensions: '+str(im.size))
print(json.dumps({'ok':True,'image':str(out),'width':1880,'height':800,'source_html':str(source),'method':'article_specific_html'},ensure_ascii=False))
