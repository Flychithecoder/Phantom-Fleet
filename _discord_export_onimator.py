"""
Export every text channel + thread in the Onimator Discord server.
Saves to orionfarm/discord-export/ as JSONL files.
Token from DISCORD_TOKEN env var, never written to disk.
"""
import os
import sys
import json
import time
import requests
from pathlib import Path

TOKEN = os.environ.get('DISCORD_TOKEN', '').strip()
if not TOKEN:
    sys.exit("set DISCORD_TOKEN env var")

GUILD_ID = '1151855354934734919'  # Onimator.com
OUT_DIR = Path(r"C:\Users\User\Desktop\Scaler Pro\orionfarm\discord-export")
OUT_DIR.mkdir(parents=True, exist_ok=True)

API = 'https://discord.com/api/v10'
HEADERS = {
    'Authorization': TOKEN,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9187 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36',
    'X-Super-Properties': 'eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiRGlzY29yZCBDbGllbnQiLCJyZWxlYXNlX2NoYW5uZWwiOiJzdGFibGUifQ==',
}

# Channel types we care about
TEXT_TYPE = 0
DM_TYPE = 1
VOICE_TYPE = 2
CATEGORY_TYPE = 4
ANNOUNCEMENT_TYPE = 5
ANNOUNCEMENT_THREAD = 10
PUBLIC_THREAD = 11
PRIVATE_THREAD = 12
STAGE = 13
DIRECTORY = 14
FORUM_TYPE = 15
MEDIA_TYPE = 16

TYPE_NAMES = {
    0: 'text', 1: 'dm', 2: 'voice', 4: 'category', 5: 'announce',
    10: 'ann_thread', 11: 'pub_thread', 12: 'priv_thread',
    13: 'stage', 14: 'dir', 15: 'forum', 16: 'media'
}

def safe_filename(name):
    out = ''
    for c in name:
        if c.isalnum() or c in ' -_':
            out += c
        else:
            out += '_'
    return out.strip()[:80]

def api(path, **params):
    url = API + path
    q = {k: v for k, v in params.items() if v is not None}
    for attempt in range(8):
        try:
            r = requests.get(url, headers=HEADERS, params=q, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"    network err, retry: {e}")
            time.sleep(2)
            continue
        if r.status_code == 429:
            retry = 2
            try:
                retry = r.json().get('retry_after', 2)
            except Exception:
                pass
            time.sleep(retry + 0.5)
            continue
        if r.status_code == 401:
            sys.exit("UNAUTHORIZED - token invalid")
        if r.status_code == 403:
            return None  # no access
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            print(f"    HTTP {r.status_code} {path}: {r.text[:200]}")
            return None
        return r.json()
    return None

def list_channels():
    return api(f'/guilds/{GUILD_ID}/channels') or []

def list_threads(channel_id):
    # List active threads in the guild (filtered to this channel later)
    data = api(f'/channels/{channel_id}/threads/archived/public', limit=100)
    threads = []
    if data:
        threads.extend(data.get('threads', []))
    data = api(f'/channels/{channel_id}/threads/archived/private', limit=100)
    if data:
        threads.extend(data.get('threads', []))
    return threads

def fetch_messages(channel_id, after_delay=0.25):
    """Paginate through all messages in a channel, newest to oldest."""
    messages = []
    before = None
    while True:
        batch = api(f'/channels/{channel_id}/messages', limit=100, before=before)
        if not batch:
            break
        messages.extend(batch)
        if len(batch) < 100:
            break
        before = batch[-1]['id']
        time.sleep(after_delay)
    return messages

def simplify_msg(m):
    return {
        'id': m.get('id'),
        'ts': m.get('timestamp'),
        'edited': m.get('edited_timestamp'),
        'author': {
            'id': (m.get('author') or {}).get('id'),
            'name': (m.get('author') or {}).get('username'),
            'global_name': (m.get('author') or {}).get('global_name'),
            'bot': (m.get('author') or {}).get('bot', False),
        },
        'content': m.get('content', ''),
        'attachments': [{'url': a.get('url'), 'filename': a.get('filename'), 'size': a.get('size')} for a in (m.get('attachments') or [])],
        'embeds': [{'title': e.get('title'), 'description': e.get('description'), 'url': e.get('url')} for e in (m.get('embeds') or [])],
        'reactions': [(r.get('emoji') or {}).get('name', '?') + 'x' + str(r.get('count', 0)) for r in (m.get('reactions') or [])],
        'mentions': [(u.get('username') or '?') for u in (m.get('mentions') or [])],
        'referenced': (m.get('referenced_message') or {}).get('id'),
        'type': m.get('type'),
    }

def save_channel(channel, messages):
    ctype = TYPE_NAMES.get(channel.get('type'), 'unk')
    fname = f"{channel['id']}__{ctype}__{safe_filename(channel.get('name', 'unnamed'))}.jsonl"
    path = OUT_DIR / fname
    with open(path, 'w', encoding='utf-8') as f:
        meta = {
            '_meta': True,
            'channel_id': channel['id'],
            'channel_name': channel.get('name'),
            'channel_type': channel.get('type'),
            'parent_id': channel.get('parent_id'),
            'topic': channel.get('topic'),
            'message_count': len(messages),
        }
        f.write(json.dumps(meta, ensure_ascii=False) + '\n')
        for m in messages:
            f.write(json.dumps(simplify_msg(m), ensure_ascii=False) + '\n')
    return path

def main():
    print("Listing channels...")
    channels = list_channels()
    if not channels:
        sys.exit("no channels returned - may lack permissions")

    # Build channel tree with categories
    categories = {c['id']: c for c in channels if c.get('type') == CATEGORY_TYPE}
    text_like = [c for c in channels if c.get('type') in (TEXT_TYPE, ANNOUNCEMENT_TYPE, FORUM_TYPE, MEDIA_TYPE)]
    print(f"  {len(channels)} total channels")
    print(f"  {len(categories)} categories")
    print(f"  {len(text_like)} text-like channels (text/announce/forum/media)")
    print()

    # Save channel index
    index_path = OUT_DIR / '_index.json'
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump({
            'guild_id': GUILD_ID,
            'guild_name': 'Onimator.com | Bumble Tinder Instagram Phones and API automation',
            'exported_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'channels': [
                {
                    'id': c['id'],
                    'name': c.get('name'),
                    'type': c.get('type'),
                    'type_name': TYPE_NAMES.get(c.get('type'), 'unk'),
                    'parent_id': c.get('parent_id'),
                    'parent_name': (categories.get(c.get('parent_id')) or {}).get('name'),
                    'topic': c.get('topic'),
                    'position': c.get('position'),
                }
                for c in channels
            ],
        }, f, indent=2, ensure_ascii=False)
    print(f"  saved channel index -> {index_path}")
    print()

    total_msgs = 0
    skipped = 0
    done = 0
    for c in text_like:
        cat = (categories.get(c.get('parent_id')) or {}).get('name', '-')
        ctype = TYPE_NAMES.get(c.get('type'), 'unk')
        label = f"[{cat}] #{c.get('name')} ({ctype})"
        print(f"-> {label}")
        msgs = fetch_messages(c['id'])
        if msgs is None:
            print(f"   NO ACCESS")
            skipped += 1
            continue
        if not msgs:
            print(f"   empty")
            # still save the metadata
            save_channel(c, [])
            continue
        p = save_channel(c, msgs)
        print(f"   {len(msgs)} msgs -> {p.name}")
        total_msgs += len(msgs)
        done += 1

        # Also fetch archived threads for this channel
        threads = list_threads(c['id'])
        if threads:
            print(f"   + {len(threads)} archived threads")
            for t in threads:
                tmsgs = fetch_messages(t['id'])
                if tmsgs:
                    save_channel(t, tmsgs)
                    total_msgs += len(tmsgs)

    print()
    print(f"=== DONE ===")
    print(f"  {done} channels exported")
    print(f"  {skipped} channels inaccessible (no perms)")
    print(f"  {total_msgs} total messages")

if __name__ == '__main__':
    main()
