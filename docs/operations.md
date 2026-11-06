# 部署与运维

本文面向把这套流水线跑在自己机器上的使用者。按「装 → 配 → 跑 → 看 → 修」的顺序组织。

---

## 1. 部署拓扑

```text
单台 Linux 主机
├── Hermes / 调度器（cron）
├── 本仓库（代码）
├── ~/.hermes/
│   ├── news/                 # 事件库、候选、健康报告、缓存
│   ├── workspace/
│   │   ├── drafts/           # 文章底稿、封面、payload、回查结果
│   │   ├── source_articles/  # 研究包
│   │   ├── covers/           # 封面工具与输出
│   │   └── history/          # 回执与通知队列
│   ├── templates/            # 规则文件（install.sh 软链）
│   ├── scripts/              # 脚本（install.sh 软链）
│   ├── tools/Horizon/        # 采集依赖
│   └── notification_config.json
└── 微信公众号（API）
```

没有数据库服务、没有消息队列、没有常驻进程。所有状态都是文件和 SQLite。

---

## 2. 安装

### 2.1 系统依赖

```bash
# Debian / Ubuntu
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip \
  chromium fonts-noto-cjk

# macOS
brew install python@3.11 chromium
```

`fonts-noto-cjk` 不是可选项：封面渲染没有中文字体时会出方块。

### 2.2 Python 依赖

```bash
cd wechat-ai-editorial-pipeline
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`：

```text
requests>=2.31
httpx>=0.27
beautifulsoup4>=4.12
Pillow>=10.0
```

### 2.3 Horizon（采集依赖）

`ai_news.py` 的 RSS / GitHub 抓取器来自 Horizon。Horizon 不在本仓库内，需要单独安装：

```bash
git clone https://github.com/<your-org>/Horizon.git ~/.hermes/tools/Horizon
python3.11 -m venv ~/.hermes/tools/Horizon/.venv
~/.hermes/tools/Horizon/.venv/bin/pip install -r ~/.hermes/tools/Horizon/requirements.txt
```

> Horizon 的虚拟环境建议用 Python 3.11。它锁定的 pydantic 版本与 Python 3.14 不兼容。

### 2.4 软链到运行目录

```bash
./install.sh
```

`install.sh` 会：

- 创建 `~/.hermes/{scripts,templates,news,workspace/covers,workspace/drafts,workspace/history}`；
- 把仓库里的脚本软链到 `~/.hermes/scripts/`；
- 把模板软链到 `~/.hermes/templates/`；
- 把 `covers/make_cover.py` 软链到 `~/.hermes/workspace/covers/`；
- 对已存在的普通文件先备份为 `.bak.<timestamp>`，不直接覆盖；
- 如果 `~/.hermes/news/sources.json` 不存在，从示例复制一份。

不想用软链，也可以直接 `cp`；软链的好处是 `git pull` 后立即生效。

---

## 3. 配置

### 3.1 采集源

```bash
cp config/sources.example.json ~/.hermes/news/sources.json
cp config/hot-sources.example.json ~/.hermes/news/hot-sources.json
```

`sources.json` 关键字段：

| 字段 | 说明 |
|---|---|
| `horizon_path` | Horizon 源码目录，支持 `~` 和环境变量 |
| `feeds[].enabled` | 设为 `false` 可临时停用某个源 |
| `repos` | GitHub release 监控列表 |
| `hn_queries` | HN 搜索词 |

`hot-sources.json` 额外包含：

- 热点补充源（IT 之家、宝玉原站）；
- 国内模型仓库；
- 创作者观察名单。

观察名单只是「发现线索」，不代表已经接通对方公众号或全量抓取。引用时必须找到原帖并核验账号身份。

### 3.2 凭据

优先级：

1. 环境变量 `WECHAT_APPID` / `WECHAT_APPSECRET`；
2. `~/.hermes/wechat_credentials.json`；
3. `WECHAT_CREDENTIALS_FILE` 指定的文件。

```bash
cat > ~/.hermes/wechat_credentials.json <<'JSON'
{"appid": "wx...", "appsecret": "..."}
JSON
chmod 600 ~/.hermes/wechat_credentials.json
```

验证：

```bash
python3 scripts/wechat_credentials.py
# {"ok": true, "appid_prefix": "wx12***", "secret_len": 32}
```

### 3.3 公众号后台

1. 设置与开发 → 基本配置 → 记下 AppID / AppSecret；
2. 同一页 → IP 白名单 → 加入服务器出口 IP（**最常见的失败原因**）；
3. 确认账号类型：订阅号没有发布接口权限，只能建草稿。

查出口 IP：

```bash
curl -sS https://api.ipify.org
```

### 3.4 通知

```bash
cp config/notification.example.json ~/.hermes/notification_config.json
chmod 600 ~/.hermes/notification_config.json
```

填入飞书群机器人地址：

```json
{
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/...",
  "signing_secret": "可留空",
  "keyword": "公众号草稿"
}
```

`notify_draft.py` 会校验 URL 必须是 `https`、域名必须是 `open.feishu.cn` 或 `open.larksuite.com`、路径必须匹配机器人 hook 格式，防止把凭据发到任意地址。

### 3.5 封面

`make_cover.py` 按以下顺序找 Chromium：

1. `CHROME_BIN` 环境变量；
2. `~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`；
3. `~/.cache/ms-playwright/chromium-1243/chrome-linux/chrome`；
4. `/usr/bin/chromium`、`/usr/bin/chromium-browser`、`/usr/bin/google-chrome`。

手动指定：

```bash
export CHROME_BIN=/usr/bin/chromium
```

验证：

```bash
python3 covers/make_cover.py \
  --title '测试<br><em>封面</em>' \
  --sub '验证 Chromium 与中文字体' \
  --kicker 'OPS · SMOKE' \
  --out /tmp/cover.png
# OK /tmp/cover.png  1880x800  ... KB
```

---

## 4. 调度

### 4.1 Hermes cron

如果使用 Hermes，创建三个任务：

```text
任务 1：热点监控
  时间：*/20 8-23 * * *
  脚本：python3 /path/to/repo/scripts/trigger.py --mode hot
  技能：agent-reach、aihot、wewrite-*、humanizer-zh、text-check-skill、wechat-automation

任务 2：20:00 兜底
  时间：0 20 * * *
  脚本：python3 /path/to/repo/scripts/trigger.py --mode fallback

任务 3：日报
  时间：2 8 * * *
  脚本：python3 /path/to/repo/scripts/trigger.py --mode daily
```

主流水线（05:30）是一个**模型任务**，不是纯脚本：它按 `docs/pipeline.md` 的十阶段提示词执行，脚本只是其中的工具。

### 4.2 system cron

```cron
SHELL=/bin/bash
PATH=/home/youruser/.local/bin:/usr/bin:/bin
HERMES_HOME=/home/youruser/.hermes

*/20 8-23 * * * cd /opt/wechat-pipeline && .venv/bin/python scripts/trigger.py --mode hot >> ~/.hermes/logs/hot.log 2>&1
0 20 * * *      cd /opt/wechat-pipeline && .venv/bin/python scripts/trigger.py --mode fallback >> ~/.hermes/logs/hot.log 2>&1
2 8 * * *       cd /opt/wechat-pipeline && .venv/bin/python scripts/trigger.py --mode daily >> ~/.hermes/logs/daily.log 2>&1
```

注意：

- cron 的 `PATH` 很短，脚本里用到 `python3`、`chromium` 时要用绝对路径或在 crontab 里设置 `PATH`；
- `trigger.py` 会剥离 `PYTHONPATH`，但如果你的环境依赖其他变量，先在 crontab 里显式导出；
- 日志要轮转，否则一年后会很大。

### 4.3 并发

- 采集锁是非阻塞的：上一轮没跑完，本轮直接返回 `already_collecting`；
- 建稿锁是阻塞的：查重和 `draft/add` 必须原子；
- 通知锁是阻塞的：队列 drain 串行。

不要同时手动跑 `publish_article.py` 和定时任务，建稿锁会挡住，但会白等。

---

## 5. 监控

### 5.1 每天看什么

| 指标 | 路径 | 正常值 |
|---|---|---|
| 采集健康 | `~/.hermes/news/health/last-hot.json` | 至少一个源 `ok` |
| 候选数量 | `~/.hermes/news/selections/YYYY-MM-DD-hot.json` | ≥1，允许 0 |
| 当天已发 | `~/.hermes/workspace/history/written.jsonl` | 0–2 条 |
| 通知队列 | `python3 scripts/notify_draft.py --status` | `pending=0` |
| 草稿回查 | `~/.hermes/workspace/drafts/*-verify.json` | 六项全 `true` |
| 最近错误 | `~/.hermes/logs/*.log` | 无连续 traceback |

### 5.2 通知状态

```bash
python3 scripts/notify_draft.py --status
# {"configured": true, "pending": 0, "sent": 42, "baseline": 3}
```

有 `pending` 说明飞书没发出去。手动 drain：

```bash
python3 scripts/notify_draft.py --drain
```

### 5.3 采集健康

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path.home()/'.hermes/news/health/last-hot.json'
d = json.loads(p.read_text(encoding='utf-8'))
print('raw:', d['raw'], 'accepted:', d['accepted_observations'])
for h in d['health']:
    print(f"{h['source']:<24} {h['status']:<22} {h.get('http_status','')}")
PY
```

常见状态：

| 状态 | 含义 | 处理 |
|---|---|---|
| `ok` | 正常 | — |
| `empty_or_unavailable` | 源没更新，或返回空 | 观察，连续多天再换源 |
| `empty_or_unparsed` | 解析器与页面结构不匹配 | 检查解析规则 |
| `failed` | 网络/HTTP 错误 | 看 `http_status`，403 可能要 UA 或代理 |

### 5.4 草稿箱核对

```bash
python3 - <<'PY'
import json, os, requests
from wechat_credentials import access_token
tok = access_token()
r = requests.post('https://api.weixin.qq.com/cgi-bin/draft/batchget',
                  params={'access_token': tok},
                  json={'offset': 0, 'count': 20, 'no_content': 1}, timeout=20)
d = json.loads(r.content.decode('utf-8'))
print('total:', d.get('total_count'))
for item in d.get('item', []):
    for a in item['content']['news_item']:
        print(item['media_id'][:12], a['title'])
PY
```

---

## 6. 故障排查

### 6.1 微信接口错误码

| 错误码 | 含义 | 处理 |
|---|---|---|
| `40001` | AppSecret 错误 / access_token 无效 | 检查凭据；重新获取 token |
| `40164` | 调用 IP 不在白名单 | 把出口 IP 加入公众号后台白名单 |
| `42001` | access_token 过期 | 重新获取；不要缓存超过 2 小时 |
| `45004` | 正文超过长度限制 | 实测 25KB 可接受；超过则拆稿或压缩 HTML |
| `40066` | 内容不合法 | 常见于正文图片地址不可访问、外链图片、非法标签 |
| `48001` | 接口未授权 | 订阅号无发布/已发表列表权限，属预期 |
| `40007` | media_id 无效 | 封面素材被删或跨账号 |
| `45009` | 接口调用频次超限 | 降低频率，等配额恢复 |

### 6.2 常见症状

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `command not found: agent-reach` | cron PATH 不含虚拟环境 | 用全路径或 `export PATH` |
| `cannot import name 'ArgsKwargs'` | Horizon 与 Hermes 的 pydantic 冲突 | 用 `trigger.py`，确认剥离 `PYTHONPATH` |
| 封面全是方块 | 没装中文字体 | `apt install fonts-noto-cjk` |
| `Chromium unavailable` | 没装 Chromium / 路径不对 | 设 `CHROME_BIN` |
| `img/caption mismatch` | 图片与 `图N｜` 数量不一致 | 改 Markdown，确保一一对应 |
| `title leaked into body` | 正文重复了总标题 | 删除正文中的标题行 |
| `digest N bytes > 70` | 摘要超字节 | 缩短到约 20 个中文字 |
| `Duplicate article blocked` | 查重命中 | 换选题/换角度；不要绕过 guard |
| `published_api: permission_denied_48001` | 订阅号无已发表列表权限 | 正常，使用本地历史；报告中注明 |
| 草稿标题乱码 | JSON 未用 `ensure_ascii=False` | 检查 payload 编码 |
| 正文图片裂图 | `mmbiz` 地址失效 / 上传未完成 | 重新上传；不要用外链 |
| Pixabay 返回 19 字节文本 | 触发限流 | 等几分钟；用 PIL 校验图片能否打开 |
| `verify failed` | `draft/get` 六项有 false | 看 `*-verify.json`，逐项修 |

### 6.3 查重误判

如果确认是新事件但被拦：

1. 看 `~/.hermes/news/health/last-upload-duplicate-check.json` 的 `matches`；
2. 对比 `previous_title`、`previous_id`；
3. 如果是标题相似但事件不同，换一个能区分主体的标题；
4. 如果是正文 shingle 重合，说明写法太像，重写开头和结构；
5. **不要**删历史回执或改 `event_id` 绕过。这会让后续查重失效。

### 6.4 上传成功但草稿箱没有

1. 确认 `draft/add` 返回了 `media_id`；
2. `draft/get` 读一次；
3. `draft/batchget` 看列表；
4. 确认账号是同一个（AppID 是否搞混）；
5. 确认不是把草稿建到了另一个运营者账号。

---

## 7. 恢复手册

### 7.1 主流水线在阶段 3 失败

- 研究包可能不完整；保留 `source_articles/` 下的内容；
- 重新跑阶段 3，不要从头抓；
- 如果原文已删除，放弃该题，换备选。

### 7.2 阶段 9 渲染失败

- 检查 Markdown 首行是否是 `# 标题`；
- 检查图片路径是否存在；
- 检查图注是否紧跟图片；
- 修好后重跑 `render_article.py`，不需要重新上传。

### 7.3 阶段 10 上传一半失败

按失败位置处理：

| 失败位置 | 已产生的副作用 | 恢复 |
|---|---|---|
| 正文图上传 | 素材库多了几张图 | 直接重跑，`image-map.json` 会复用同哈希的图 |
| 封面上传 | 素材库多了一张图 | 重跑会复用同哈希封面 |
| `draft/add` | 可能已建草稿 | 先 `draft/batchget` 查重，再决定是否重跑 |
| `draft/get` | 草稿已存在但回查失败 | 不要重复建稿；先读草稿，修 payload 后 `draft/update`（如支持）或删稿重建 |
| 记账 | 草稿已存在，回执未写 | 手动 `mark_written.py --media-id ...` |
| 通知 | 草稿与回执都在，通知未发 | `notify_draft.py --drain` |

`publish_article.py` 的 `image-map.json` 按 SHA256 缓存已上传图片和封面。重跑时文件没变就不会重复上传，这一点在恢复时很有用。

### 7.4 当天重复发了同一事件

1. 立即在后台删除后发的那篇（如果还没发布）；
2. 如果已发布，不要删，改为在文末/评论区说明；
3. 查 `written.jsonl` 和 `delivered` 表，确认是哪个环节漏了；
4. 如果是 `event_id` 不同导致，检查 `same_event()` 的阈值；
5. 把这次事件加入 `deferred`，避免短期内再写。

### 7.5 通知一直 pending

```bash
python3 scripts/notify_draft.py --status
python3 scripts/notify_draft.py --drain
```

如果 `last_error` 是 `feishu_http_4xx`：webhook 失效或签名错误；重新生成机器人。
如果是 `feishu_transport_*`：网络问题；检查出口。

---

## 8. 备份与保留

### 8.1 必须备份

| 路径 | 原因 |
|---|---|
| `~/.hermes/news/events.sqlite3` | 事件账本，丢了就无法查重 |
| `~/.hermes/workspace/history/*.jsonl` | 交付回执 |
| `~/.hermes/workspace/history/draft_notifications.sqlite3` | 通知队列 |
| `~/.hermes/wechat_credentials.json` | 凭据（单独加密保管） |
| `~/.hermes/notification_config.json` | 通知配置（含 webhook） |

### 8.2 不必备份

- `news/cache/`：可重新抓；
- `workspace/drafts/*-preview.html`：可重新渲染；
- `workspace/source_articles/*/images/`：原文图可重下，但建议保留，避免原文删除后无法复现。

### 8.3 保留策略

- 事件库：永久保留；
- 回执：永久保留；
- 草稿：保留最近 90 天；
- 研究包：保留最近 180 天；
- 日志：保留 30 天，按周轮转。

---

## 9. 升级

```bash
cd wechat-ai-editorial-pipeline
git pull
. .venv/bin/activate
pip install -r requirements.txt
./install.sh          # 更新软链，已有普通文件会备份
```

升级后做三件事：

1. 离线渲染一篇示例稿；
2. 生成一张封面，确认 Chromium 与字体正常；
3. 用 `--dry-run` 跑一次 `publish_article.py`，确认 payload 结构没变。

不要在生产任务运行期间升级。

---

## 10. 安全运维

- 凭据文件权限 `600`，不要提交到 git；
- 不要把 `notification_config.json` 贴到聊天或 issue；
- 定期轮换 AppSecret：后台重置 → 更新凭据文件 → 跑一次 `wechat_credentials.py`；
- 出口 IP 变化后，先更新白名单，再跑任务；
- 不要在共享机器上把仓库放在世界可读目录；
- 日志里不要打印 token、secret、webhook；现有代码已避免，但自建脚本要注意。

---

## 11. 相关文档

- [架构与状态机](architecture.md)
- [十阶段执行手册](pipeline.md)
- [选题与真实性规则](editorial-policy.md)
- [安全设计与去重闸门](security.md)
