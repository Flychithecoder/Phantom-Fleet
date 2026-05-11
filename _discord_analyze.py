"""
Analyze the Onimator Discord export.
Focus channels: general, phones-instagram, news, knowledge-base, pro-tips,
                NomixCloner/general, NomixCloner/announcements

Outputs:
  _analysis/top_authors.md       - top 30 most active authors per focus channel
  _analysis/pro_posts.md         - every substantive (>100 char) post from top authors
  _analysis/keyword_index.md     - keyword-indexed snippets for technical terms
  _analysis/channel_summaries.md - per-channel summary
  _analysis/full_small.md        - full content of small channels
"""
import json
import os
import re
from pathlib import Path
from collections import Counter, defaultdict

EXPORT_DIR = Path(r"C:\Users\User\Desktop\Scaler Pro\orionfarm\discord-export")
OUT_DIR = Path(r"C:\Users\User\Desktop\Scaler Pro\orionfarm\discord-export\_analysis")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Focus channel filenames (substring match)
FOCUS = {
    'general_community': '1151856048580345936__text',       # community general
    'phones-instagram': '1151856175499980873',
    'news': '1207644611388907550',
    'knowledge-base': '1413205888927268967',
    'pro-tips_resources': '1358074652877918350',
    'nomixcloner_general': '1238789938703634565',
    'nomixcloner_announce': '1446225802663428268',
}

TECH_KEYWORDS = [
    'proxy', '4g', '5g', 'mobile proxy', 'residential', 'webshare', 'iproyal', 'soax', 'bright data',
    'appcloner', 'app cloner', 'nomixcloner', 'nomix', 'clone', 'clones', 'repackage',
    'shadowban', 'shadow', 'ban', 'banned', 'dead', 'killed', 'died', 'pva',
    'warming', 'warmup', 'warm up', '48 hour', '48h', 'warm',
    'samsung', 's9', 's10', 'pixel', 'android', 'rooted', 'root', 'magisk', 'xposed', 'frida',
    'sim', 'imei', 'android id', 'android_id', 'gaid', 'advertising id',
    'locale', 'timezone', 'tz', 'language',
    'rate limit', 'action block', 'checkpoint', 'challenge', 'verification', 'verify',
    'script', 'recipe', 'macro', 'delay', 'tap', 'swipe',
    'price', 'cost', 'plan', 'subscription', '$', 'usd', 'eur',
    'dm', 'follow', 'unfollow', 'like', 'story', 'reel', 'post', 'comment',
    'onlyfans', 'fanvue', 'scaleher', 'funnel',
    'api', 'endpoint', 'token', 'cookie', 'session',
    'touch', 'type', 'keyboard', 'adbkeyboard',
    'detection', 'detect', 'undetectable', 'stealth', 'anti',
    'instagram', 'tiktok', 'threads', 'reddit', 'snapchat', 'tinder', 'bumble', 'hinge',
    'brayn', 'founder', 'staff',
]

def load_channel(file_path):
    messages = []
    meta = None
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get('_meta'):
                meta = obj
                continue
            messages.append(obj)
    # Messages arrive newest-first; reverse for chronological
    messages.reverse()
    return meta, messages

def find_focus_files():
    files = {}
    for key, needle in FOCUS.items():
        for fn in os.listdir(EXPORT_DIR):
            if needle in fn and fn.endswith('.jsonl'):
                files[key] = EXPORT_DIR / fn
                break
    return files

def escape_md(s):
    if s is None:
        return ''
    # Collapse whitespace but preserve paragraph breaks
    s = re.sub(r'\r', '', s)
    return s.strip()

def is_substantive(content):
    if not content:
        return False
    c = content.strip()
    if len(c) < 100:
        return False
    # Skip if it's just a URL or mention
    if re.match(r'^https?://\S+$', c):
        return False
    if re.match(r'^<@!?\d+>$', c):
        return False
    return True

def keyword_hits(content):
    lower = (content or '').lower()
    hits = []
    for kw in TECH_KEYWORDS:
        if kw in lower:
            hits.append(kw)
    return hits

def author_stats(messages):
    by_author = defaultdict(lambda: {'count': 0, 'substantive': 0, 'total_chars': 0, 'global_name': None})
    for m in messages:
        author = m.get('author') or {}
        name = author.get('name') or 'unknown'
        by_author[name]['count'] += 1
        content = m.get('content', '') or ''
        by_author[name]['total_chars'] += len(content)
        if is_substantive(content):
            by_author[name]['substantive'] += 1
        if not by_author[name]['global_name']:
            by_author[name]['global_name'] = author.get('global_name')
    return by_author

def write_top_authors(all_authors):
    lines = ['# Top authors across focus channels\n']
    lines.append('Sorted by substantive post count (posts >100 chars).\n\n')
    lines.append('| Rank | Author | Global name | Total msgs | Substantive (>100c) | Total chars | Chars/msg |')
    lines.append('|------|--------|-------------|-----------:|--------------------:|------------:|----------:|')
    combined = defaultdict(lambda: {'count': 0, 'substantive': 0, 'total_chars': 0, 'global_name': None})
    for ch_name, authors in all_authors.items():
        for name, stats in authors.items():
            combined[name]['count'] += stats['count']
            combined[name]['substantive'] += stats['substantive']
            combined[name]['total_chars'] += stats['total_chars']
            if not combined[name]['global_name']:
                combined[name]['global_name'] = stats['global_name']
    ranked = sorted(combined.items(), key=lambda x: (-x[1]['substantive'], -x[1]['total_chars']))
    for i, (name, s) in enumerate(ranked[:50], 1):
        cpm = s['total_chars'] / max(1, s['count'])
        lines.append(f"| {i} | {name} | {s['global_name'] or ''} | {s['count']} | {s['substantive']} | {s['total_chars']} | {cpm:.0f} |")
    (OUT_DIR / 'top_authors.md').write_text('\n'.join(lines), encoding='utf-8')
    return [name for name, _ in ranked[:30]]

def write_pro_posts(channels_data, top_authors_set):
    lines = [f"# Pro posts — substantive (>100 char) messages from top 30 authors\n"]
    lines.append(f"Top authors used for filtering: {', '.join(sorted(top_authors_set))}\n\n")
    lines.append('---\n')
    total = 0
    for ch_name, (meta, messages) in channels_data.items():
        lines.append(f"\n## {ch_name}  ({meta.get('channel_name', '?')})\n")
        count_here = 0
        for m in messages:
            author = (m.get('author') or {}).get('name', 'unknown')
            if author not in top_authors_set:
                continue
            content = m.get('content', '') or ''
            if not is_substantive(content):
                continue
            ts = m.get('ts', '')[:10]
            lines.append(f"\n**[{ts}] {author}**")
            # Clean content for markdown
            body = escape_md(content).replace('\n\n\n', '\n\n')
            lines.append(body)
            lines.append('')
            count_here += 1
            total += 1
        lines.append(f"\n*({count_here} pro posts from this channel)*\n")
    lines.insert(2, f"Total pro posts across focus channels: {total}\n\n")
    (OUT_DIR / 'pro_posts.md').write_text('\n'.join(lines), encoding='utf-8')

def write_keyword_index(channels_data):
    hits = defaultdict(list)
    for ch_name, (meta, messages) in channels_data.items():
        for m in messages:
            content = m.get('content', '') or ''
            if len(content) < 20:
                continue
            kws = keyword_hits(content)
            if not kws:
                continue
            author = (m.get('author') or {}).get('name', '?')
            ts = m.get('ts', '')[:10]
            snippet = content[:500].replace('\n', ' ')
            for kw in kws:
                hits[kw].append((ts, author, ch_name, snippet, len(content)))

    lines = ['# Keyword-indexed Discord snippets\n']
    lines.append('Every technical keyword with up to 30 most substantive matches (sorted by length, longest first).\n\n')

    for kw in sorted(hits.keys(), key=lambda k: -len(hits[k])):
        rows = hits[kw]
        rows.sort(key=lambda r: -r[4])  # longest first
        lines.append(f"\n## `{kw}` — {len(rows)} hits\n")
        for ts, author, ch, snip, ln in rows[:30]:
            lines.append(f"- **[{ch} · {ts} · {author}]** {snip[:400]}")
        if len(rows) > 30:
            lines.append(f"*({len(rows) - 30} more hits truncated)*")
    (OUT_DIR / 'keyword_index.md').write_text('\n'.join(lines), encoding='utf-8')

def write_small_full(channels_data, small_names):
    lines = ['# Full content of small/critical channels\n']
    for ch_name in small_names:
        if ch_name not in channels_data:
            continue
        meta, messages = channels_data[ch_name]
        lines.append(f"\n## {ch_name} ({meta.get('channel_name', '?')}) — {len(messages)} msgs\n")
        for m in messages:
            author = (m.get('author') or {}).get('name', '?')
            ts = m.get('ts', '')[:10]
            content = escape_md(m.get('content', '') or '')
            if not content:
                continue
            lines.append(f"\n**[{ts}] {author}:** {content}")
    (OUT_DIR / 'full_small.md').write_text('\n'.join(lines), encoding='utf-8')

def write_channel_summaries(channels_data):
    lines = ['# Per-channel summary\n']
    for ch_name, (meta, messages) in channels_data.items():
        lines.append(f"\n## {ch_name}")
        lines.append(f"- channel name: {meta.get('channel_name', '?')}")
        lines.append(f"- total messages: {len(messages)}")
        if not messages:
            continue
        authors = Counter((m.get('author') or {}).get('name', '?') for m in messages)
        lines.append(f"- unique authors: {len(authors)}")
        lines.append(f"- top 10 by msg count:")
        for name, cnt in authors.most_common(10):
            lines.append(f"  - {name}: {cnt}")
        substantive = [m for m in messages if is_substantive(m.get('content', ''))]
        lines.append(f"- substantive posts (>100c): {len(substantive)}")
        first = messages[0].get('ts', '')[:10]
        last = messages[-1].get('ts', '')[:10]
        lines.append(f"- date range: {first} to {last}")
    (OUT_DIR / 'channel_summaries.md').write_text('\n'.join(lines), encoding='utf-8')

def main():
    files = find_focus_files()
    print(f"Found focus files: {list(files.keys())}")

    channels_data = {}
    all_authors = {}
    for key, path in files.items():
        print(f"  loading {key}: {path.name}")
        meta, messages = load_channel(path)
        channels_data[key] = (meta, messages)
        all_authors[key] = author_stats(messages)
        print(f"    {len(messages)} messages, {len(all_authors[key])} authors")

    # 1) Top authors
    top30 = write_top_authors(all_authors)
    print(f"  wrote top_authors.md")

    # 2) Pro posts from top 30 across focus channels
    top_set = set(top30)
    write_pro_posts(channels_data, top_set)
    print(f"  wrote pro_posts.md")

    # 3) Keyword index
    write_keyword_index(channels_data)
    print(f"  wrote keyword_index.md")

    # 4) Small channels full dump
    small = ['news', 'knowledge-base', 'pro-tips_resources', 'nomixcloner_announce']
    write_small_full(channels_data, small)
    print(f"  wrote full_small.md")

    # 5) Per-channel summary
    write_channel_summaries(channels_data)
    print(f"  wrote channel_summaries.md")

    print("\nDone. Outputs in _analysis/")

if __name__ == '__main__':
    main()
