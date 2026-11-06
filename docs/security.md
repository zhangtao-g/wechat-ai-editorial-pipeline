# 安全设计与去重闸门

这套系统要在一个真实账号上无人值守地跑，安全边界必须写清楚。本文分四部分：凭据、权限、内容、数据。

---

## 1. 威胁模型

| 威胁 | 后果 | 现有控制 |
|---|---|---|
| AppSecret 泄露 | 他人可调用账号接口、建稿、改素材 | 凭据只在环境变量/600 文件；仓库不含真实值；日志不打印 |
| access_token 泄露 | 2 小时内可调用接口 | 每次运行重新获取，不落盘、不写日志 |
| 误调发布接口 | 未经人工审核的内容对外 | 代码层拒绝 `freepublish/submit`；只走草稿 |
| 重复内容 | 读者流失、账号降权 | 三层去重；上传闸门 |
| 未核实事实 | 信用损失、法律风险 | 研究包、来源分级、合规扫描 |
| 图片版权 | 投诉、赔偿 | 原文图优先、图注标来源、图库图标「示意图」 |
| Prompt 注入 | 抓到恶意页面，指令被模型执行 | 外部内容只作为资料；不执行页面指令 |
| 本地路径泄露 | 暴露用户名/目录结构 | 上传前检查 `Path.home()` 与 `images/` |
| 通知 webhook 泄露 | 他人可向群里发消息 | 配置文件 600；异常日志不写 URL |
| 数据丢失 | 无法查重、无法复现 | 事件库、回执、研究包备份 |

不在威胁模型内：

- 多租户隔离；
- 针对主机入侵的防御；
- 微信账号被盗；
- 供应链攻击（pip 包被投毒）。

---

## 2. 凭据

### 2.1 读取顺序

```text
WECHAT_APPID / WECHAT_APPSECRET
        ↓ 没有则读
WECHAT_CREDENTIALS_FILE（默认 ~/.hermes/wechat_credentials.json）
        ↓ 都没有
报错退出，不尝试猜测
```

### 2.2 代码约束

`scripts/wechat_credentials.py`：

- 不在异常信息里拼接 secret；
- `__main__` 只打印 `appid[:4] + "***"` 和 `len(secret)`；
- 不使用 `eval` / `exec`；
- 不把凭据写入任何文件。

### 2.3 仓库约束

公开仓库前做了以下扫描：

```bash
grep -rnE "wx[0-9a-f]{16}|appsecret|github_pat_|webhook|api[_-]?key" .
```

确认仓库内没有：

- 真实 AppID / AppSecret；
- GitHub PAT；
- 飞书 webhook；
- Pixabay / 其他图库 Key；
- 生产服务器 IP；
- 真实草稿 `media_id`；
- 历史文章与读者数据。

### 2.4 轮换

```text
后台重置 AppSecret
  → 更新 ~/.hermes/wechat_credentials.json
  → python3 scripts/wechat_credentials.py
  → 跑一次 --dry-run
  → 确认旧 secret 已失效
```

---

## 3. 权限边界

### 3.1 只进草稿箱

| 接口 | 是否调用 | 说明 |
|---|---|---|
| `cgi-bin/token` | 是 | 获取 access_token |
| `media/uploadimg` | 是 | 正文图片 |
| `material/add_material` | 是 | 封面永久素材 |
| `draft/add` | 是 | 建草稿 |
| `draft/get` | 是 | 回查 |
| `draft/batchget` | 是 | 查重、列表 |
| `draft/delete` | 仅显式清理 | 自动流程不删 |
| `freepublish/submit` | **否** | 代码层拒绝 |
| `freepublish/batchget` | 尝试 | 订阅号可能 48001 |

### 3.2 自动发布的硬阻断

`wechat_duplicate_guard.py` 的 `install()`：

```python
def guarded(session, method, url, **kw):
    p = urlsplit(url)
    if p.hostname != 'api.weixin.qq.com':
        return original(session, method, url, **kw)
    if p.path.endswith('/submit'):
        raise ValueError('Automatic publication disabled; use the reviewed draft workflow')
    if p.path not in ('/cgi-bin/draft/add', '/cgi-bin/freepublish/submit'):
        return original(session, method, url, **kw)
    # 查重后才放行 draft/add
```

这不是提示词约束，是运行时异常。任何调用 `freepublish/submit` 的代码都会直接失败。

### 3.3 为什么还要保留 `freepublish/batchget`

它是查重的重要数据源：已发表文章可能不在草稿箱里，但仍在传播。订阅号没有权限时返回 `48001`，此时：

- 不阻断建稿；
- 退回本地回执和长期归档；
- 在报告里明确 `published_api: permission_denied_48001`；
- **不声称**检查了全部微信历史。

---

## 4. 去重闸门

### 4.1 为什么需要运行时闸门

提示词可以写「不要重复」，但模型可能：

- 忘记查历史；
- 把同一事件当成新事件；
- 换个标题继续写；
- 绕过 `publish_article.py` 直接调接口。

所以最后一道防线必须在代码里，而且要在**请求发出前**生效。

### 4.2 比对逻辑

```text
输入：候选文章列表（title, content, content_source_url）
数据源：
  A. 草稿箱全量（实时）
  B. 已发表列表（可能 48001）
  C. 本地回执（written.jsonl / daily_written.jsonl）
  D. 长期归档（wechat-archive.sqlite3）

对每篇候选，与每个历史条目比较：
  1. 规范化标题完全相同 → same_title
  2. same_event(title_a, title_b) → same_event_title
  3. 规范化原文 URL 相同且路径长度 > 5 → same_original_article
  4. 正文 12 字 shingle 重合度：
       同栏目 ≥ 0.65 → same_body_despite_title_change
       跨栏目 ≥ 0.90 → same_body_despite_title_change
  5. 候选之间互相比较 → within_upload_*

命中任一 → 抛 ValueError，draft/add 不发出
```

### 4.3 阈值怎么定的

- **同栏目 0.65**：同一事件的不同写法，正文重合度通常很高；0.65 能抓住「换标题不换内容」。
- **跨栏目 0.90**：日报是新闻汇总，热点是深度研究，允许共享事件和原文；只有整篇几乎相同才拦。这个规则是 2026-10-20 用户明确要求的，覆盖了早期「跨栏目一律禁止」的做法。
- **URL 路径长度 > 5**：避免 `https://example.com/` 这种根路径误判。
- **12 字 shingle**：中文按字符切，能抗住少量改写；太短会误判，太长会漏判。

### 4.4 闸门的副作用

- 每次建稿都要拉全量草稿箱，草稿多时会慢（35 篇约几秒到几十秒）；
- 草稿箱很大时（几百篇），`no_content=0` 会消耗较多流量；
- 如果草稿箱接口超时，建稿会失败——这是故意的，宁可失败，不可漏检。

### 4.5 不要做的事

- 不要为了「先发出去」删历史回执；
- 不要改 `event_id` 绕过；
- 不要注释掉 `install()`；
- 不要自写 `requests.post('.../draft/add')` 绕过 guard；
- 不要在 guard 失败后手动调接口补发。

这些都会让三层去重失效，且很难事后发现。

---

## 5. 内容安全

### 5.1 事实

- 关键事实必须能追到原文；
- 来源分级 A–E（见 `editorial-policy.md`）；
- 未核实标 `unverified`；
- 传闻单独处理，标题体现不确定性；
- 实测稿必须有原始输出哈希。

### 5.2 合规

阶段 6 是硬性步骤：

1. 敏感词扫描（本地词库）；
2. 按《微信公众平台运营规范》逐条对审；
3. 命中必须改掉并重扫到干净；
4. 高风险无法处理 → 放弃该稿。

### 5.3 Prompt 注入

抓取的外部页面是不可信数据。系统约定：

- 页面内容只作为资料，不执行其中指令；
- 不把页面里的「忽略之前的指令」当命令；
- 不根据页面内容修改系统提示词；
- 不把页面里的链接当可信来源，必须核验域名。

---

## 6. 数据安全

### 6.1 权限

| 文件 | 权限 | 原因 |
|---|---|---|
| `wechat_credentials.json` | `600` | 含 AppSecret |
| `notification_config.json` | `600` | 含 webhook |
| `draft_notifications.sqlite3` | `600` | 含草稿标题与 ID |
| `events.sqlite3` | 默认 | 含文章标题与 URL |
| `written.jsonl` | 默认 | 含 `media_id` |

### 6.2 不进仓库

`.gitignore` 排除：

```text
.env
*.local
__pycache__/
*.py[cod]
.venv/
workspace/
drafts/
history/
*.sqlite3
*.sqlite3-wal
*.sqlite3-shm
```

仓库只含代码、模板、示例配置，不含任何运行数据。

### 6.3 日志

- 不打印 token、secret、webhook；
- 不打印完整 payload（可能含正文）；
- 错误信息只保留 `errcode`、`errmsg`、HTTP 状态；
- 通知模块明确注释：`Do not log exception text: network errors can contain the secret webhook.`

### 6.4 保留

- 事件库、回执：永久；
- 草稿：90 天；
- 研究包：180 天；
- 日志：30 天。

---

## 7. 开源前检查清单

如果你要 fork 这套系统并公开自己的版本，逐项确认：

- [ ] `grep -rnE "wx[0-9a-f]{16}" .` 无命中；
- [ ] `grep -rn "appsecret" .` 只命中示例/文档；
- [ ] `grep -rnE "github_pat_|ghp_" .` 无命中；
- [ ] `grep -rn "open.feishu.cn/open-apis/bot" .` 只命中示例；
- [ ] `grep -rnE "[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}" .` 无生产 IP；
- [ ] `git status` 没有 `.env`、凭据、草稿、数据库；
- [ ] `git log -p` 里没有历史泄露（如果之前提交过，必须重写历史）；
- [ ] 示例配置里的 Key 都是 `REPLACE_ME` / `YOUR_KEY`；
- [ ] README 没有贴真实 `media_id`、账号二维码、后台截图。

---

## 8. 残余风险

| 风险 | 说明 | 建议 |
|---|---|---|
| 凭据在内存中 | Python 进程可被同机高权限用户读取 | 单机专用；不要放共享主机 |
| 数据未加密 | SQLite 与 JSONL 是明文 | 全盘加密；备份加密 |
| 单账号 | 没有权限隔离 | 多账号时拆实例 |
| 接口变化 | 微信可能调整字段/权限 | 定期跑 `--dry-run` 回归 |
| 模型误判 | 选题/事实判断仍可能错 | 人工发布前复核 |
| 闸门绕过 | 有人手动改代码 | 代码评审；生产环境只读部署 |
| 图片版权 | 图库图仍可能有第三方 logo | 逐张 vision 复核；图注标来源 |

---

## 9. 相关文档

- [架构与状态机](architecture.md)
- [十阶段执行手册](pipeline.md)
- [部署与运维](operations.md)
- [选题与真实性规则](editorial-policy.md)
