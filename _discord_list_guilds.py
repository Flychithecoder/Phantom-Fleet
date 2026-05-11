"""
List all Discord guilds the user is a member of.
Token is read from DISCORD_TOKEN env var — never stored on disk.
"""
import os
import sys
import json
import time
import requests

TOKEN = os.environ.get('DISCORD_TOKEN', '').strip()
if not TOKEN:
    print("ERROR: set DISCORD_TOKEN env var")
    sys.exit(1)

API = 'https://discord.com/api/v10'
HEADERS = {
    'Authorization': TOKEN,
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9187 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36',
    'X-Super-Properties': 'eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiRGlzY29yZCBDbGllbnQiLCJyZWxlYXNlX2NoYW5uZWwiOiJzdGFibGUifQ==',
}

def get(path):
    url = API + path
    for attempt in range(5):
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            retry = r.json().get('retry_after', 2)
            print(f"  rate limit, sleep {retry}s")
            time.sleep(retry + 0.5)
            continue
        if r.status_code == 401:
            print(f"  UNAUTHORIZED — token invalid/expired")
            sys.exit(2)
        if r.status_code == 403:
            print(f"  FORBIDDEN on {path}")
            return None
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} on {path}: {r.text[:200]}")
            return None
        return r.json()
    return None

# 1. Verify token
me = get('/users/@me')
if not me:
    print("Token verification failed")
    sys.exit(2)
print(f"Logged in as: {me.get('username')} ({me.get('id')})")
print()

# 2. List guilds
guilds = get('/users/@me/guilds')
if not guilds:
    print("No guilds returned")
    sys.exit(2)

print(f"Found {len(guilds)} guilds:")
print()
matches = []
for g in guilds:
    name = g.get('name', '?')
    gid = g.get('id', '?')
    owner = g.get('owner', False)
    perms = g.get('permissions', '?')
    marker = ' '
    if 'onimator' in name.lower() or 'oni' in name.lower()[:6]:
        marker = '*'
        matches.append((gid, name))
    print(f"  {marker} [{gid}] {name}")

print()
if matches:
    print(f"=== ONIMATOR MATCHES ===")
    for gid, name in matches:
        print(f"  {gid}  {name}")
else:
    print("No Onimator-like guild found. User is in guilds:")
    for g in guilds:
        print(f"  - {g.get('name')}")
