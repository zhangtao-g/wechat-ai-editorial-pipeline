# 十阶段执行手册

这份手册是给「执行任务的 agent」看的，不是给读者看的。每一步都写清楚：做什么、用什么命令、产物是什么、什么情况下必须停下。

主流水线在每天 05:30 启动，目标 07:00 前进入草稿箱。十个阶段必须一口气跑完，不按时间点切分，不把阶段拆到别的任务里。

---

## 阶段 1：情报抓取

### 目标

拿到过去 24–48 小时的 AI 新闻候选，并保留「原始发布时间、来源、原文链接」三要素。

### 动作

1. 确认日期与时间：

```bash
date '+%Y-%m-%d %H:%M:%S %Z'
```

2. 拉 AIHOT 两个入口：

```bash
curl -sS -A 'aihot-skill/2.0.0 (+https://aihot.news/aihot-skill/)' \
  https://aihot.news/api/v1/agent/latest -o /tmp/aihot-latest.txt
curl -sS -A 'aihot-skill/2.0.0 (+https://aihot.news/aihot-skill/)' \
  https://aihot.news/api/v1/agent/hot -o /tmp/aihot-hot.txt
```

3. 跑采集器（RSS / GitHub / HN）：

```bash
python3 scripts/trigger.py --mode hot
```

4. 用可用的搜索工具补中文源（36 氪、虎嗅、V2EX、IT 之家等）。

### 产物

- `~/.hermes/news/events.sqlite3` 新增观察；
- `~/.hermes/news/selections/YYYY-MM-DD-hot.json` 候选；
- `~/.hermes/news/health/last-hot.json` 源健康度。

### 通过标准

- 至少有一个源的 `status=ok`；
- 候选里的 `published` 来自原文，不是抓取时间；
- 海外条目保留北京时间 00:00–05:00 区间，这是最早的第一手料。

### 停止条件

- 所有源都失败，且 AIHOT 也拿不到 → 报错，不发稿；
- 候选为空 → 正常结束，允许当天空缺。

---

## 阶段 2：选题定稿

### 目标

从候选里选出一个「读者关心、事实站得住、能写出增量」的题，而不是「热度最高」的题。

### 打分

| 维度 | 权重 | 判断依据 |
|---|---:|---|
| 热度 | 30% | 榜位、来源数量、社交讨论 |
| 相关度 | 40% | 国内读者是否用得上、是否影响钱/工作/隐私 |
| 切入价值 | 30% | 有没有新事实、能不能给出判断、是否有对比空间 |

情绪型、测评型选题额外 +2。

### 优先级

1. **DeepSeek**：官方或经证实的模型、API、定价、开源、合作、团队与生态变动；
2. **腾讯 WorkBuddy**（腾讯龙虾）：版本、定价与 Credits、专家/Skills 市场、企微/微信接入、企业落地；
3. **其他国内 AI**：通义千问、豆包、Kimi、智谱 GLM、MiniMax、混元、文心、可灵、即梦等；
4. 海外精选：OpenAI / Anthropic / Google 等有大众影响的消息，占比约 20%。

优先级只决定先看谁，不降低门槛。上一档只有传闻、旧闻、已写事件 → 视同无合格选题，顺延。

### 铁律

- 破圈：AI + 全民话题，禁止纯技术评测；
- 选题公式：「我用 AI 做了 XX 让人惊讶的事」「AI 帮我发现了 XX 规律」；
- 避开近 7 天写过的事件；
- 不硬凑：没有合格选题就不发。

### 产物

一个主选题 + 两个备选，写清：

```text
事件：
主体（公司/机构/产品）：
目标读者：
读者收益：
可核实的一手来源：
文章类型：news_analysis / creator_research / comparison_analysis / comparison_test / hands_on / rumor_check
地域：domestic / overseas
为什么现在写：
主要风险：
```

### 通过标准

- 主体能在标题里直接点名；
- 至少有一个官方/原始来源；
- 与历史回执不重复（`ai_news.py validate` 会再查一次）。

---

## 阶段 3：调研核验

### 目标

把「媒体报道」变成「可追溯的事实清单」。不是找更多文章，而是找**原始出处**。

### 动作

1. 打开官方博客、官方文档、价格页、GitHub release、论文原文、X 原帖；
2. 每条关键事实记录：内容、来源链接、发布时间、来源类型（official / media / creator / release）、核验状态（confirmed / unverified）；
3. 抓原文与图片：

```bash
python3 scripts/fetch_hot_article.py \
  --url 'https://example.com/original-article' \
  --out ~/.hermes/workspace/source_articles/2026-11-06/evt-xxxx
```

4. 建研究包：

```text
~/.hermes/workspace/source_articles/YYYY-MM-DD/<event_id>/
├── research.md
├── sources.json
├── testing-evidence.json   # 仅实测稿
└── images/
    ├── 001.jpg
    └── manifest.json
```

`research.md` 必须包含：

- 事件时间线（谁、什么时候、做了什么）；
- 已证实 / 未证实 / 无法证实；
- 作者归属（如果是创作者的探索）；
- 读者收益；
- 不能推出的结论；
- 文章类型与地域判断。

### 通过标准

- 每个关键数字都能在原文找到；
- 传闻有明确的不确定性标注；
- 没有把「代码痕迹」当成「正式发布」；
- 没有把「多个转载」当成「独立证实」。

### 停止条件

- 只有二手摘要，拿不到原文 → 放弃该题；
- 关键事实无法核实 → 降级为 rumor_check，或放弃。

---

## 阶段 4：写作

### 目标

1500–2000 字，第一人称，口语化，有具体数字，承认失败。

### 结构

```text
开头：一个具体场景 / 一个反常识的事实（不要复读标题）
背景：这件事为什么现在发生
主体：3–5 个事实 + 每个事实的解释
转折：限制、失败、没解决的问题
判断：读者该不该用、该不该花钱、该关注什么
结尾：一句人话，不喊口号
```

### 风格

- 打工人日记，不是教科书；
- 具体数字优先于形容词；
- 承认失败和不确定性；
- 不用「首先/其次/最后」的列表腔；
- 不写投资分析；
- 不在正文重复文章总标题。

### 产物

`~/.hermes/workspace/drafts/YYYY-MM-DD-draft.md`，第一行是 `# 完整标题`。

### 通过标准

- 字数 1500–2000；
- 每个关键事实有来源；
- 没有编造的亲测细节；
- 读起来像一个人写的，不像模型总结的。

---

## 阶段 5：去 AI 味 + 审稿

### 动作

1. 去 AI 味：删空话、删重复、删模板化过渡、拆长句、把抽象换成具体；
2. 审稿：逐条核对事实来源、观点是否站得住、有没有过度推断；
3. 直接改稿，不要只列问题。

### 常见 AI 味

| 症状 | 改法 |
|---|---|
| 「随着……的发展」 | 删掉，直接说事 |
| 「不仅……而且……」 | 拆成两句 |
| 「值得注意的是」 | 删掉 |
| 「总的来说」 | 删掉，或换成具体判断 |
| 每段都是「观点 + 三点论据」 | 打乱结构，有的段落只讲一个细节 |
| 形容词堆砌 | 换成数字、动作、结果 |

### 通过标准

- 没有空话和重复；
- 每个观点都能在正文找到依据；
- 读者能复述「这篇讲了什么、跟我有什么关系」。

---

## 阶段 6：合规检测（不可跳）

### 动作

1. 敏感词扫描：

```bash
bash ~/.hermes/skills/gzh/text-check-skill/scripts/check.sh \
  --target_file /absolute/path/to/final.md
```

> 这个 skill 是本地环境的一部分，不在本仓库内。没有安装时，用等价的自建词库扫描，但不能跳过。

2. 按《微信公众平台运营规范》逐条对审：

- 政治敏感、历史人物、领土表述；
- 金融承诺、收益保证、荐股；
- 医疗功效、保健品；
- 未证实的指控、名誉风险；
- 诱导分享、诱导关注；
- 侵权（图片、引语、商标）。

3. 命中敏感词必须改掉，并重扫到干净。

### 产物

合规报告：命中词、行号、处理方式、剩余风险。

### 停止条件

- 命中敏感词未清零 → 不排版；
- 存在无法处理的高风险 → 放弃该稿。

---

## 阶段 7：标题定稿

### 目标

让读者在信息流里知道「谁、做了什么、跟我有什么关系」。

### 规则

- 必须点名具体公司、机构、人物或产品；
- 说清它做了什么；
- 不用「AI 巨头」「某公司」「新模型」「刚刚发布」让读者猜；
- 不设人为字数/字节上限，不按长度截断；
- 微信编辑器上限 64 字，draft 实测可接受 39 字 / 71 字节；
- 钩子放在前 10 字；
- 数字必须能在原文找到；
- 型号、版本、对标对象不能升级或降级。

### 四种可用结构

| 类型 | 例子 | 适用 |
|---|---|---|
| 数字冲突 | 「DeepSeek 把价格砍到 1/10，谁在买单」 | 定价、性能、对比 |
| 悬念反问 | 「AI 替你回消息，为什么你更累了」 | 体验、争议 |
| 反差对比 | 「同一个任务，Claude 花了 3 分钟，它花了 3 小时」 | 实测、对比 |
| 情绪代入 | 「我妈用 AI 写的第一份简历，比我写得好」 | 生活、破圈 |

### 产物

3 个候选 + 1 个定稿，说明选择理由。

### 通过标准

- 主体明确；
- 数字可核实；
- 读者一眼知道「这条新闻跟我有关」。

---

## 阶段 8：封面 + 配图

### 封面

固定模板：

```bash
python3 covers/make_cover.py \
  --title '苹果把AI<br>塞进<em>客厅</em>' \
  --sub '299 美元的屏，苹果智能还是没来' \
  --kicker 'AI · 消费电子' \
  --accent '#00FF9D' \
  --out ~/.hermes/workspace/drafts/2026-11-06-cover.png
```

- `title` 用 `<br>` 换行，两行、每行 ≤6 个汉字最好；
- `<em>…</em>` 包住强调词，会染成强调色并发光；
- `accent`：`#00FF9D` 荧光绿（默认）、`#FB7185` 警示红、`#60A5FA` 科技蓝、`#FBBF24` 琥珀；
- 输出 1880×800，必须校验尺寸。

独立设计封面：

```bash
python3 scripts/render_hot_cover_html.py \
  --html /absolute/path/cover.html \
  --out /absolute/path/cover.png
```

### 正文配图

优先级：

1. 原文图片（保留原始字节，不改、不裁、不压缩）；
2. 官方图表 / 截图（注明机构、口径、日期）；
3. 真实照片（Pixabay 等，图注必须写「示意图」）；
4. 自绘示意图（图注写「本人制图」）。

禁止：

- 把示意图伪装成实拍；
- 把官方图裁掉水印或改字；
- 用热链；
- 用与正文数字对不上的库存图垫图。

### 图片校验

```bash
python3 - <<'PY'
from PIL import Image
from pathlib import Path
for p in sorted(Path('images').glob('*')):
    if p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}:
        with Image.open(p) as im:
            print(p.name, im.size, im.format)
PY
```

微信 `uploadimg` 不接受 webp，先转 PNG。

### 通过标准

- 封面 1880×800，中文无乱码，主体名准确；
- 正文图片数与图注数一致；
- 每张图都能说清「这是什么、数据从哪来、有什么限制」。

---

## 阶段 9：排版 + 校验

### 渲染

```bash
python3 scripts/render_article.py \
  --input ~/.hermes/workspace/drafts/2026-11-06-final.md \
  --out ~/.hermes/workspace/drafts/2026-11-06-body.html \
  --preview ~/.hermes/workspace/drafts/2026-11-06-preview.html \
  --date 2026.11.06 \
  --column AI热点
```

### 三组数校验

```bash
python3 - <<'PY'
import re
from pathlib import Path
html = Path('/path/to/body.html').read_text(encoding='utf-8')
print('img     =', html.count('<img'))
print('caption =', len(re.findall(r'图\d+｜', html)))
print('h2      =', html.count('<h2'))
PY
```

- `<img>` 数 = `图N｜` 数 = 实际图片数；
- 正文不出现文章总标题；
- 不出现代码块反引号；
- 不出现本地绝对路径；
- 不出现 `images/` 相对路径（上传前必须换成 `mmbiz` 地址）。

### 版式检查

- 正文 16px、行高 1.9；
- 章节标题 20px + 4px 绿色左边线；
- 图注 13px 中文；
- 没有显式白色/浅灰背景（暗黑模式会留白底）；
- 手机宽度 390px 下没有孤字换行、没有横向滚动。

### 通过标准

三组数一致、无标题泄漏、无本地路径、手机预览正常。

---

## 阶段 10：上传草稿箱 + 回查（不可跳）

### 一条命令

```bash
python3 scripts/publish_article.py \
  --md ~/.hermes/workspace/drafts/2026-11-06-final.md \
  --column AI热点 \
  --date 2026.11.06 \
  --digest '一句话摘要，≤70字节' \
  --cover-title '两行<br><em>标题</em>' \
  --cover-sub '副标题' \
  --cover-kicker 'AI · 热点' \
  --cover-accent '#00FF9D' \
  --source-url 'https://原文地址'
```

### 内部顺序

1. 读 Markdown，首行标题，摘要字节检查；
2. 渲染正文与预览；
3. 图片/图注一致性检查；
4. 生成封面并校验尺寸；
5. 上传正文图，替换 `mmbiz` 地址，校验文件哈希；
6. 上传封面，拿 `thumb_media_id`；
7. 生成 payload，调用 `wechat_duplicate_guard.py`；
8. 查重（草稿箱 + 已发表 + 本地历史 + 归档）；
9. `draft/add`；
10. `draft/get` 回查六项；
11. `mark_written.py` 写回执；
12. `notify_draft.py` 发通知。

### 回查六项

| 项 | 通过条件 |
|---|---|
| `title` | 读出的标题与本地完全一致 |
| `digest` | 读出的摘要与传入一致 |
| `imgs` | 正文 `<img>` 数 = 上传图片数 |
| `img_sigs` | 每张 `mmbiz` 地址签名顺序一致 |
| `thumb` | `thumb_media_id` 与封面素材一致 |
| `no_local_path` | 不含 `images/` 或本地 home 路径 |

六项全过才算完成。任何一项失败，非零退出，不写成功回执。

### 最终校验 JSON（热点）

```json
{
  "event_id": "evt-...",
  "subject": "DeepSeek",
  "title": "完整标题",
  "body": "正文 Markdown",
  "url": "https://原文地址",
  "new_progress_verified": false,
  "article_type": "news_analysis",
  "region": "domestic",
  "reader_relevance": "国内开发者与 API 用户的实际成本影响"
}
```

实测稿额外需要：

```json
{
  "article_type": "comparison_test",
  "testing_evidence": "/absolute/path/to/testing-evidence.json"
}
```

`testing-evidence.json`：

```json
{
  "task": "长文总结对比",
  "tested_at": "2026-11-06T10:00:00+08:00",
  "method": "同一篇 8000 字文章，同一提示词，各跑 3 次",
  "runs": [
    {
      "model": "Claude",
      "version": "Sonnet 4.6",
      "access": "web",
      "settings": "默认，联网关闭",
      "prompt_path": "/abs/research/prompt.txt",
      "output_path": "/abs/research/run1.md",
      "output_sha256": "..."
    }
  ]
}
```

### 日报 JSON

```json
{
  "date": "2026.11.06",
  "title": "每天60秒看懂AI时间｜某条完整新闻标题",
  "lead": "导语",
  "items": [
    {
      "title": "新闻标题",
      "body": "两句话说明",
      "highlight": "一句看点",
      "source": "来源名",
      "url": "https://原文"
    }
  ],
  "closing": "今日观察"
}
```

约束：1–16 条，实际发布建议 10–16 条；每条 URL 必须是真实 HTTP(S)，禁止 `example.com`。

---

## 交付清单

一篇稿子完成时，必须能回答：

- [ ] 选题是什么，为什么选它；
- [ ] 3 个标题候选，定稿是哪个，为什么；
- [ ] 核心事实清单，每条带链接与核验状态；
- [ ] 合规检测结果，命中词是否清零；
- [ ] 封面生成命令与尺寸校验结果；
- [ ] 正文图片数量、来源、图注是否一致；
- [ ] `media_id` 与 `draft/get` 回查结果；
- [ ] 各阶段实际耗时；
- [ ] 通知是否送达（或进了队列）。

---

## 相关文档

- [架构与状态机](architecture.md)
- [部署与运维](operations.md)
- [选题与真实性规则](editorial-policy.md)
- [安全设计与去重闸门](security.md)
