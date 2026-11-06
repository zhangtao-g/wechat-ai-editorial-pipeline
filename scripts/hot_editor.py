"""Audience-first hot selection. Ranking is discovery, never verified evidence."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re

POLICY_PATH = Path(
    os.environ.get(
        'HOT_EDITORIAL_POLICY',
        str(Path(__file__).resolve().parent.parent / 'templates/hot-editorial-policy.md'),
    )
)

POLICY_VERSION = 'domestic-deepseek-workbuddy-20261102'
DOMESTIC = re.compile(r'deepseek|深度求索|workbuddy|codebuddy|腾讯龙虾|buddy\s*one|qwen|kimi|moonshot|minimax|glm|zhipu|doubao|hunyuan|ernie|seedance|seedream|kling|baidu|alibaba|tencent|bytedance|国产|国内|中国|豆包|千问|通义|混元|文心|智谱|月之暗面|可灵|即梦|海螺|阶跃|讯飞|扣子|飞书|钉钉|百度|腾讯|阿里|字节|小米|华为|夸克|秘塔|纳米|快手', re.I)
# 2026-11-02 用户指定的选题优先级：DeepSeek > WorkBuddy > 其他国内 AI
FIRST_TIER = re.compile(r'deepseek|深度求索', re.I)
SECOND_TIER = re.compile(r'workbuddy|腾讯龙虾|buddy\s*one', re.I)
MAJOR = re.compile(r'openai|chatgpt|anthropic|claude|google|gemini|deepmind|谷歌', re.I)
PUBLIC = re.compile(r'价格|定价|收费|免费|会员|开放|用户|隐私|泄露|就业|工作|生活|学习|教育|办公|手机|视频|语音|图片|图像|对比|测试|评测|实测|工作流|智能体|搜索|文档|表格|写作|发布|上线|开源|price|pricing|free|launch|release|privacy|video|image|voice|agent|search|compar|benchmark|workflow', re.I)
EXPLORATION = re.compile(r'对比|评测|实测|测试|研究|探索|工作流|复现|失败|benchmark|compar|workflow|experiment', re.I)
MAJOR_CHANGE = re.compile(r'正式发布|全面开放|降价|免费开放|重大|泄露|隐私|就业|launch|pricing|privacy', re.I)
RUMOR = re.compile(r'传闻|据传|爆料|小道|疑似|rumou?r|leak', re.I)


def classify(item, articles):
    text = item['title'] + ' ' + item.get('summary', '')
    creator = any(a.get('kind') == 'creator' for a in articles)
    # Creator nationality or Chinese reporting alone is not a domestic event.
    domestic = bool(DOMESTIC.search(text))
    exploration = bool(EXPLORATION.search(text))
    relevant = bool(PUBLIC.search(text))
    if not relevant or not (domestic or creator and exploration or MAJOR.search(text)):
        return None
    rumor = bool(RUMOR.search(text))
    substantive = any(a.get('kind') in ('official', 'release', 'creator', 'media') for a in articles)
    # An aggregator-only rumor cannot independently wake the writing agent.
    if rumor and not substantive:
        return None
    score = 45 + (25 if domestic else 0) + (15 if exploration else 0) + (10 if substantive else 0)
    # 选题优先级：DeepSeek 优先于 WorkBuddy，WorkBuddy 优先于其他国内 AI。
    # topic_tier 参与硬排序；传闻不能靠优先级插队。
    if FIRST_TIER.search(text):
        score += 15
        topic_tier = 0
    elif SECOND_TIER.search(text):
        score += 8
        topic_tier = 1
    else:
        topic_tier = 2
    if rumor:
        topic_tier = 2
    score += 5 if item.get('age_hours', 49) <= 24 else 0
    score -= 15 if rumor else 0
    return {
        'region': 'domestic' if domestic else 'overseas',
        'editorial_score': score,
        'topic_tier': topic_tier,
        'candidate_type': 'creator_research' if creator else ('comparison_opportunity' if exploration else 'news'),
        'evidence_status': 'requires_original_verification',
        'additional_article_eligible': bool(domestic and (exploration or MAJOR_CHANGE.search(text)) and score >= 85),
    }


def selection(news, mode):
    today = news.now().astimezone(news.CST).date().isoformat()
    midnight = dt.datetime.combine(news.now().astimezone(news.CST).date(), dt.time(), tzinfo=news.CST).isoformat()
    with news.db() as c:
        deliveries = list(c.execute("SELECT DISTINCT media_id FROM delivered WHERE channel='hot' AND julianday(at)>=julianday(?)", (midnight,)))
        count = len(deliveries)
        if count >= 2 or mode == 'fallback' and count:
            return None
        chosen = []
        for eid, rows in news.grouped(c, 24 * 14).items():
            rows = [a for a in rows if a.get('kind') == 'creator' or news.parse_time(a['published']) >= news.now() - dt.timedelta(hours=48)]
            if not rows:
                continue
            lease = c.execute('SELECT until_at FROM reservations WHERE event_id IN (?,?) AND owner LIKE ?', ('hot:' + eid, eid, 'hot:%')).fetchone()
            delay = c.execute('SELECT until_at FROM deferred WHERE event_id IN (?,?) ORDER BY until_at DESC LIMIT 1', ('hot:' + eid, eid)).fetchone()
            if any(r and news.parse_time(r[0]) > news.now() for r in (lease, delay)):
                continue
            if news.historical_match(c, eid, rows, 'hot'):
                continue
            item = news.candidate(eid, rows)
            meta = classify(item, rows)
            if meta is None or count and not meta['additional_article_eligible']:
                continue
            item.update(meta)
            item['new_progress_requires_verification'] = False
            chosen.append(item)
        # Preserve true AIHOT ranks in metadata, but never use a top-N gate.
        # 2026-11-02 用户指定：国内优先，其内 DeepSeek > WorkBuddy > 其他国内 AI，再按编辑分。
        chosen.sort(key=lambda x: (x['region'] != 'domestic', x.get('topic_tier', 2), -x['editorial_score'], -news.parse_time(x['published_at']).timestamp(), x['event_id']))
        # Recent verified editorial receipts constrain overseas selections after activation.
        policy_path = news.ROOT / 'hot-policy.json'
        policy = json.loads(policy_path.read_text(encoding='utf-8')) if policy_path.exists() else {}
        since = policy.get('activated_at', news.stamp())
        history = list(c.execute("SELECT DISTINCT d.media_id,e.title FROM delivered d JOIN events e ON e.id=d.event_id WHERE d.channel='hot' AND julianday(d.at)>=julianday(?)", (since,)))
        domestic_n = sum(bool(DOMESTIC.search(r['title'])) for r in history)
        foreign_n = len(history) - domestic_n
        if foreign_n >= max(1, (domestic_n + 1) // 4):
            chosen = [x for x in chosen if x['region'] == 'domestic']
        if not chosen:
            # One bounded creator-discovery opportunity a day, not every 20 minutes.
            done = news.ROOT / 'research-checks' / (today + '.json')
            hour = news.now().astimezone(news.CST).hour
            if count or done.exists() or hour < 10:
                return None
            chosen = [{'event_id': 'research-request-' + today, 'candidate_type': 'research_request',
                       'title': '定向发现国内大众AI话题、模型对比和创作者原始研究',
                       'research_queries': ['宝玉 AI 模型 对比 工作流', '数字生命卡兹克 AI 实测', '归藏 AI 探索 研究', '李继刚 AI 工作流', 'DeepSeek 豆包 千问 Kimi 对比'],
                       'not_a_news_event': True, 'policy_path': str(POLICY_PATH)}]
        payload = {'mode': mode, 'policy_version': POLICY_VERSION, 'candidates': chosen[:5],
                   'written_today': count, 'quota_left': max(0, 2 - count),
                   'instructions': 'Verify originals. No AIHOT rank gate. Read hot-editorial-policy.md. Research requests are not events.'}
        path = news.ROOT / 'selections' / f'{today}-{mode}.json'
        news.write_json(path, payload)
        # Omit clock/age changes so monitor output stays stable within a candidate set.
        stable = dict(payload)
        stable['candidates'] = [{k: v for k, v in x.items() if k not in ('age_hours', 'source_count')} for x in payload['candidates']]
        stable['selection_path'] = str(path)
        return stable


def validate_testing(payload, home):
    article_type = payload.get('article_type')
    if article_type not in ('news_analysis', 'creator_research', 'comparison_analysis', 'comparison_test', 'hands_on', 'rumor_check'):
        raise ValueError('Hot article requires an explicit editorial article_type')
    if payload.get('region') not in ('domestic', 'overseas') or not payload.get('reader_relevance', '').strip():
        raise ValueError('Hot article requires region and concrete reader_relevance')
    own_test = re.search(r'我(?:们)?(?:亲自|实际)?(?:实测|亲测|测试了)|本次实测|我们的测试', payload.get('title', '') + payload.get('body', ''))
    if article_type not in ('comparison_test', 'hands_on'):
        if own_test or article_type == 'comparison_analysis' and re.search(r'实测|亲测', payload.get('title', '')):
            raise ValueError('Own test claims require a test article_type and raw evidence')
        return
    root = (home / 'workspace').resolve()
    def checked(value):
        p = Path(value)
        if not p.is_absolute() or not p.resolve().is_relative_to(root):
            raise ValueError('Testing evidence must be an absolute file inside the article workspace')
        if not p.is_file() or not p.stat().st_size:
            raise ValueError('Testing evidence file missing or empty')
        return p.resolve()
    evidence_path = checked(payload.get('testing_evidence', ''))
    data = json.loads(evidence_path.read_text(encoding='utf-8'))
    if not all(data.get(k) for k in ('task', 'tested_at', 'method')):
        raise ValueError('Testing evidence lacks task/date/method')
    runs = data.get('runs', [])
    models = set()
    for run in runs:
        if not all(run.get(k) for k in ('model', 'version', 'access', 'settings', 'prompt_path', 'output_path', 'output_sha256')):
            raise ValueError('Test run lacks reproducible conditions or raw files')
        prompt = checked(run['prompt_path']); output = checked(run['output_path'])
        if not prompt.is_relative_to(evidence_path.parent) or not output.is_relative_to(evidence_path.parent):
            raise ValueError('Raw results must belong to this article research directory')
        if hashlib.sha256(output.read_bytes()).hexdigest() != run['output_sha256']:
            raise ValueError('Raw output hash does not match testing evidence')
        models.add(run['model'])
    if len(models) < (2 if article_type == 'comparison_test' else 1):
        raise ValueError('Insufficient distinct tested models')


def main():
    import ai_news as news
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['research-done'])
    p.add_argument('--report', required=True)
    args = p.parse_args()
    report = Path(args.report).resolve()
    if not report.is_relative_to((news.HOME / 'workspace').resolve()) or not report.is_file() or report.stat().st_size < 20:
        raise ValueError('Save a substantive research-check report inside workspace first')
    today = news.now().astimezone(news.CST).date().isoformat()
    news.write_json(news.ROOT / 'research-checks' / (today + '.json'), {'at': news.stamp(), 'report': str(report)})
    print(json.dumps({'ok': True, 'research_checked': today}))


if __name__ == '__main__':
    main()
