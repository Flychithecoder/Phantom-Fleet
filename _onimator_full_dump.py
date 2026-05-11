"""
Comprehensive read-only dump of every SQLite database under the Onimator install.
Extracts: schemas, row counts, sample rows, and aggregates.
REDACTS: passwords, tokens, 2fa_secret, cookies fields.
Writes output to _analysis/onimator_intel.md (markdown) + onimator_intel.json (structured).
"""
import sqlite3
import os
import json
import re
import shutil
import tempfile
from pathlib import Path
from collections import defaultdict

ROOT = Path(r"C:\Onimator\full_igbot_14.1.8.1")
OUT_DIR = Path(r"C:\Users\User\Desktop\Scaler Pro\orionfarm\discord-export\_analysis")
OUT_MD = OUT_DIR / "onimator_intel.md"
OUT_JSON = OUT_DIR / "onimator_intel.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Fields to redact in dumps (case-insensitive substring match)
REDACT_FIELDS = {
    'password', 'pass', 'pwd', 'token', '2fa', 'cookie', 'session',
    'auth', 'secret', 'private', 'proxy_password', 'email_password'
}

SAMPLE_ROWS = 3  # how many sample rows to dump per table


def is_redact_field(col_name):
    col_lower = col_name.lower()
    return any(r in col_lower for r in REDACT_FIELDS)


def redact_value(val, col_name):
    if val is None:
        return None
    if is_redact_field(col_name):
        s = str(val)
        if len(s) > 8:
            return s[:3] + '***' + s[-2:]
        return '***'
    s = str(val)
    if len(s) > 200:
        return s[:200] + '...'
    return s


def find_all_dbs(root):
    dbs = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip dependency folders
        if any(skip in dirpath for skip in [
            'dist-info', '__pycache__', 'adbutils', 'cryptography',
            'django', 'flask', 'gevent', 'greenlet', 'numpy', 'PIL',
            'PyQt5', 'lxml', 'scrapy', 'selenium', 'uiautomator2',
            'pymongo', 'sqlalchemy', 'matplotlib', 'fontTools',
            'altgraph', 'astroid', 'bson', 'certifi', 'cffi',
            'charset_normalizer', 'contourpy', 'imageio', 'importlib',
            'IPython', 'jedi', 'jiter', 'kiwisolver', 'markupsafe',
            'multidict', 'MySQLdb', 'parso', 'psutil', 'pycparser',
            'pydantic', 'pytz', 'pywin32', 'pyzmq', 'setuptools',
            'tcl', 'tk', 'wcwidth', 'win32', 'yaml', 'yarl', 'zmq',
            'zope', 'eel', 'attrs', 'adbutils', 'aiohttp', 'frozenlist',
            'http', 'jinja2', 'idna', 'referencing', 'jsonschema',
            'mongo', 'pkg_resources', 'requests', 'urllib3'
        ]):
            continue
        for fn in filenames:
            if fn.endswith('.db') or fn.endswith('.sqlite') or fn.endswith('.sqlite3'):
                dbs.append(Path(dirpath) / fn)
    return dbs


def safe_open_db(db_path):
    """Open SQLite DB in read-only mode. Handle locked files by copying to temp."""
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        # Fallback: copy to temp and read
        try:
            tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
            tmp.close()
            shutil.copy2(db_path, tmp.name)
            return sqlite3.connect(tmp.name)
        except Exception as e:
            return None


def dump_db(db_path):
    result = {
        'path': str(db_path),
        'rel_path': str(db_path.relative_to(ROOT)) if db_path.is_relative_to(ROOT) else str(db_path),
        'size_bytes': db_path.stat().st_size,
        'tables': {},
        'error': None,
    }
    try:
        conn = safe_open_db(db_path)
        if conn is None:
            result['error'] = 'Could not open (locked or corrupted)'
            return result
        cur = conn.cursor()
        cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cur.fetchall()
        for name, create_sql in tables:
            table_info = {
                'create_sql': (create_sql or '').strip()[:600],
                'columns': [],
                'row_count': 0,
                'sample_rows': [],
            }
            try:
                cur.execute(f"PRAGMA table_info({name})")
                cols = cur.fetchall()
                table_info['columns'] = [c[1] for c in cols]

                cur.execute(f"SELECT COUNT(*) FROM {name}")
                table_info['row_count'] = cur.fetchone()[0]

                if table_info['row_count'] > 0:
                    cur.execute(f"SELECT * FROM {name} LIMIT {SAMPLE_ROWS}")
                    rows = cur.fetchall()
                    for row in rows:
                        sample = {}
                        for i, col_name in enumerate(table_info['columns']):
                            if i < len(row):
                                sample[col_name] = redact_value(row[i], col_name)
                        table_info['sample_rows'].append(sample)
            except Exception as e:
                table_info['error'] = str(e)[:200]
            result['tables'][name] = table_info
        conn.close()
    except Exception as e:
        result['error'] = str(e)[:300]
    return result


def analyze_notification_db(db_path):
    """Deeper analysis of notificationdatabase.db to extract per-account activity."""
    analysis = {'path': str(db_path), 'per_account_stats': {}, 'per_device_stats': {}, 'action_types': {}}
    try:
        conn = safe_open_db(db_path)
        if conn is None:
            return analysis
        cur = conn.cursor()

        # Try to get per-account counts (likely columns: account, deviceid, notification, date)
        try:
            cur.execute("""
                SELECT account, deviceid, COUNT(*) as action_count,
                       MIN(date) as first_action, MAX(date) as last_action
                FROM notifications
                GROUP BY account
                ORDER BY action_count DESC
                LIMIT 500
            """)
            for row in cur.fetchall():
                analysis['per_account_stats'][row[0]] = {
                    'device': row[1],
                    'count': row[2],
                    'first': row[3],
                    'last': row[4],
                }
        except Exception as e:
            analysis['per_account_error'] = str(e)[:200]

        # Per-device counts
        try:
            cur.execute("""
                SELECT deviceid, COUNT(*) as cnt,
                       COUNT(DISTINCT account) as accounts
                FROM notifications
                GROUP BY deviceid
                ORDER BY cnt DESC
            """)
            for row in cur.fetchall():
                analysis['per_device_stats'][row[0]] = {
                    'action_count': row[1],
                    'unique_accounts': row[2],
                }
        except Exception:
            pass

        # Action type frequency (if notification column has categorical values)
        try:
            cur.execute("""
                SELECT notification, COUNT(*) as cnt
                FROM notifications
                GROUP BY notification
                ORDER BY cnt DESC
                LIMIT 30
            """)
            for row in cur.fetchall():
                analysis['action_types'][str(row[0])[:80]] = row[1]
        except Exception:
            pass

        conn.close()
    except Exception as e:
        analysis['error'] = str(e)[:200]
    return analysis


def analyze_iguser_db(db_path):
    """Analyze the 7,412-user scraped target database."""
    analysis = {'path': str(db_path), 'total_users': 0}
    try:
        conn = safe_open_db(db_path)
        if conn is None:
            return analysis
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        analysis['total_users'] = cur.fetchone()[0]

        # Sample stats
        try:
            cur.execute("SELECT COUNT(DISTINCT username) FROM users")
            analysis['unique_usernames'] = cur.fetchone()[0]
        except Exception:
            pass

        try:
            cur.execute("""
                SELECT is_private, is_verified, is_business_account, COUNT(*)
                FROM users
                GROUP BY is_private, is_verified, is_business_account
            """)
            analysis['category_breakdown'] = [
                {'private': r[0], 'verified': r[1], 'business': r[2], 'count': r[3]}
                for r in cur.fetchall()
            ]
        except Exception:
            pass

        # Followers distribution
        try:
            cur.execute("""
                SELECT
                    CASE
                        WHEN CAST(followers AS INTEGER) < 100 THEN '0-99'
                        WHEN CAST(followers AS INTEGER) < 1000 THEN '100-999'
                        WHEN CAST(followers AS INTEGER) < 10000 THEN '1k-10k'
                        WHEN CAST(followers AS INTEGER) < 100000 THEN '10k-100k'
                        WHEN CAST(followers AS INTEGER) < 1000000 THEN '100k-1M'
                        ELSE '1M+'
                    END as bucket,
                    COUNT(*) as cnt
                FROM users
                WHERE followers IS NOT NULL AND followers != ''
                GROUP BY bucket
            """)
            analysis['followers_distribution'] = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            pass

        conn.close()
    except Exception as e:
        analysis['error'] = str(e)[:200]
    return analysis


def main():
    all_dbs = find_all_dbs(ROOT)
    print(f"Found {len(all_dbs)} .db files under {ROOT}")

    all_dumps = {}
    for db in all_dbs:
        print(f"  reading {db.relative_to(ROOT)}")
        all_dumps[str(db.relative_to(ROOT))] = dump_db(db)

    # Special analyses
    notif_db = ROOT / 'notificationdatabase.db'
    notif_analysis = analyze_notification_db(notif_db) if notif_db.exists() else None

    iguser_db = ROOT / 'iguserdatabase.db'
    iguser_analysis = analyze_iguser_db(iguser_db) if iguser_db.exists() else None

    # Write JSON
    final = {
        'databases': all_dumps,
        'notification_analysis': notif_analysis,
        'iguser_analysis': iguser_analysis,
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(final, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {OUT_JSON}")

    # Write markdown report
    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write("# Onimator Full Database Intel\n\n")
        f.write(f"**Scanned:** {ROOT}\n")
        f.write(f"**Databases found:** {len(all_dbs)}\n\n")
        f.write("---\n\n")

        # Sort databases by path for readability
        for rel_path in sorted(all_dumps.keys()):
            info = all_dumps[rel_path]
            f.write(f"## `{rel_path}`\n\n")
            f.write(f"- **Size:** {info['size_bytes']} bytes\n")
            if info.get('error'):
                f.write(f"- **Error:** {info['error']}\n\n")
                continue
            if not info['tables']:
                f.write("- *(empty database)*\n\n")
                continue
            for table_name, table_info in info['tables'].items():
                f.write(f"\n### `{table_name}` — {table_info['row_count']} rows\n\n")
                if table_info.get('error'):
                    f.write(f"*Error: {table_info['error']}*\n\n")
                    continue
                f.write(f"**Columns:** `{', '.join(table_info['columns'])}`\n\n")
                if table_info['sample_rows']:
                    f.write("**Sample rows** (passwords/tokens redacted):\n\n")
                    for i, row in enumerate(table_info['sample_rows'], 1):
                        f.write(f"_Row {i}:_\n")
                        for k, v in row.items():
                            f.write(f"- `{k}`: {v}\n")
                        f.write("\n")
            f.write("---\n\n")

        # Notification analysis
        if notif_analysis:
            f.write("## Notification database deep analysis\n\n")
            f.write(f"### Per-device action counts\n\n")
            for dev, stats in list(notif_analysis.get('per_device_stats', {}).items())[:30]:
                f.write(f"- `{dev}`: {stats['action_count']} actions across {stats['unique_accounts']} accounts\n")
            f.write("\n### Action type frequency (top 30)\n\n")
            for action, cnt in list(notif_analysis.get('action_types', {}).items())[:30]:
                f.write(f"- `{action}`: {cnt}\n")
            f.write(f"\n### Top 50 accounts by action count\n\n")
            top_accounts = sorted(notif_analysis.get('per_account_stats', {}).items(),
                                   key=lambda x: -x[1]['count'])[:50]
            f.write("| Account | Device | Actions | First seen | Last seen |\n")
            f.write("|---|---|---:|---|---|\n")
            for acct, stats in top_accounts:
                f.write(f"| {acct} | {stats['device']} | {stats['count']} | {stats['first']} | {stats['last']} |\n")
            f.write("\n")

        # iguser analysis
        if iguser_analysis:
            f.write("## iguserdatabase.db (scraped target pool)\n\n")
            f.write(f"- **Total users:** {iguser_analysis.get('total_users')}\n")
            f.write(f"- **Unique usernames:** {iguser_analysis.get('unique_usernames')}\n")
            if 'followers_distribution' in iguser_analysis:
                f.write("\n**Followers distribution of targets:**\n\n")
                for bucket, cnt in iguser_analysis['followers_distribution'].items():
                    f.write(f"- {bucket}: {cnt}\n")
            if 'category_breakdown' in iguser_analysis:
                f.write("\n**Category breakdown:**\n\n")
                for cat in iguser_analysis['category_breakdown']:
                    f.write(f"- private={cat['private']}, verified={cat['verified']}, business={cat['business']}: {cat['count']}\n")
            f.write("\n")

    print(f"Wrote {OUT_MD}")


if __name__ == '__main__':
    main()
