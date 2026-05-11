"""
Concise Onimator summary — just the numbers Phantom Fleet needs.
Reads the full dump JSON and the raw DBs for targeted queries.
"""
import json
import sqlite3
import os
import shutil
import tempfile
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(r"C:\Onimator\full_igbot_14.1.8.1")
OUT = Path(r"C:\Users\User\Desktop\Scaler Pro\orionfarm\discord-export\_analysis\onimator_summary.md")


def safe_open(db_path):
    try:
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        shutil.copy2(db_path, tmp.name)
        return sqlite3.connect(tmp.name), tmp.name
    except Exception:
        return None, None


def list_device_folders():
    """List device folders at root (Samsung serials)."""
    devices = []
    for d in ROOT.iterdir():
        if d.is_dir() and (d.name.startswith('RF8N') or len(d.name) == 16):
            devices.append(d.name)
    return sorted(devices)


def count_accounts_per_device():
    """For each device folder, count active accounts (subfolders, excluding .trash, .stm)."""
    result = {}
    for d in list_device_folders():
        device_path = ROOT / d
        if not device_path.is_dir():
            continue
        accounts = []
        trashed = 0
        for item in device_path.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                # Check if it has an accounts.db or data.db (sign of a real account folder)
                if (item / 'data.db').exists() or (item / 'accounts.db').exists() or (item / 'stats.db').exists():
                    accounts.append(item.name)
        # Count trashed
        trash_path = device_path / '.trash'
        if trash_path.exists():
            trashed = len([t for t in trash_path.iterdir() if t.is_dir()])
        result[d] = {'active': accounts, 'active_count': len(accounts), 'trashed_count': trashed}
    return result


def read_top_level_dbs():
    """Read the 8 top-level system databases."""
    results = {}
    top_level = ['devices.db', 'settings.db', 'new_settings.db', 'iguserdatabase.db',
                 'notificationdatabase.db', 'license.db', 'segmento.db', 'storyprocessed.db']
    for db in top_level:
        path = ROOT / db
        if not path.exists():
            continue
        conn, tmpfile = safe_open(path)
        if not conn:
            continue
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            db_info = {'tables': {}}
            for t in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    cnt = cur.fetchone()[0]
                    cur.execute(f"SELECT * FROM {t} LIMIT 5")
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                    db_info['tables'][t] = {
                        'columns': cols,
                        'row_count': cnt,
                        'samples': rows,
                    }
                except Exception as e:
                    db_info['tables'][t] = {'error': str(e)[:120]}
            results[db] = db_info
        finally:
            conn.close()
            if tmpfile:
                try:
                    os.unlink(tmpfile)
                except Exception:
                    pass
    return results


def analyze_notification_history():
    """Analyze per-account action history from notificationdatabase.db."""
    path = ROOT / 'notificationdatabase.db'
    if not path.exists():
        return {}
    conn, tmpfile = safe_open(path)
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        # Columns: rowid, deviceid, account, notification, date, time
        cur.execute("SELECT COUNT(*) FROM notifications")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT account) FROM notifications")
        unique_accounts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT deviceid) FROM notifications")
        unique_devices = cur.fetchone()[0]
        # Top 30 most-active accounts
        cur.execute("""
            SELECT account, deviceid, COUNT(*) as cnt, MIN(date) as first, MAX(date) as last
            FROM notifications
            GROUP BY account
            ORDER BY cnt DESC
            LIMIT 30
        """)
        top = cur.fetchall()
        # Per-device totals
        cur.execute("""
            SELECT deviceid, COUNT(*) as actions, COUNT(DISTINCT account) as accounts
            FROM notifications
            GROUP BY deviceid
            ORDER BY actions DESC
        """)
        per_device = cur.fetchall()
        # Action type distribution
        cur.execute("""
            SELECT notification, COUNT(*) as cnt
            FROM notifications
            GROUP BY notification
            ORDER BY cnt DESC
            LIMIT 30
        """)
        action_types = cur.fetchall()
        return {
            'total_actions': total,
            'unique_accounts': unique_accounts,
            'unique_devices': unique_devices,
            'top_30_accounts': top,
            'per_device': per_device,
            'action_types': action_types,
        }
    finally:
        conn.close()
        if tmpfile:
            try:
                os.unlink(tmpfile)
            except Exception:
                pass


def list_settings_folders():
    """List the Settings/ persona config folders."""
    settings_root = ROOT / 'Settings'
    if not settings_root.exists():
        return []
    result = []
    for item in settings_root.iterdir():
        if item.is_dir():
            result.append(item.name)
    return sorted(result)


def analyze_settings_accounts_db():
    """Read the accounts.db under each Settings/ persona folder."""
    settings_root = ROOT / 'Settings'
    result = {}
    if not settings_root.exists():
        return result
    for persona_folder in settings_root.iterdir():
        if not persona_folder.is_dir():
            continue
        accounts_db = persona_folder / 'accounts.db'
        if not accounts_db.exists():
            result[persona_folder.name] = {'note': 'no accounts.db'}
            continue
        conn, tmpfile = safe_open(accounts_db)
        if not conn:
            result[persona_folder.name] = {'error': 'could not open'}
            continue
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            persona_info = {'tables': {}}
            for t in tables:
                try:
                    cur.execute(f"PRAGMA table_info({t})")
                    cols = [r[1] for r in cur.fetchall()]
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    cnt = cur.fetchone()[0]
                    cur.execute(f"SELECT * FROM {t} LIMIT 50")
                    rows = cur.fetchall()
                    persona_info['tables'][t] = {
                        'columns': cols,
                        'count': cnt,
                        'rows': rows,
                    }
                except Exception as e:
                    persona_info['tables'][t] = {'error': str(e)[:120]}
            result[persona_folder.name] = persona_info
        finally:
            conn.close()
            if tmpfile:
                try:
                    os.unlink(tmpfile)
                except Exception:
                    pass
    return result


def redact(v, col=''):
    if v is None:
        return 'NULL'
    col_l = col.lower() if col else ''
    redact_substrs = ['password', 'pass', 'pwd', 'token', '2fa', 'cookie', 'secret', 'auth']
    if any(s in col_l for s in redact_substrs):
        s = str(v)
        if len(s) > 6:
            return s[:3] + '***'
        return '***'
    s = str(v)
    if len(s) > 80:
        return s[:80] + '...'
    return s


def main():
    print("Starting Onimator summary extraction...")
    devices = list_device_folders()
    print(f"  {len(devices)} device folders found")

    account_map = count_accounts_per_device()
    print(f"  Counted accounts per device")

    top_level = read_top_level_dbs()
    print(f"  Read {len(top_level)} top-level DBs")

    notif = analyze_notification_history()
    print(f"  Analyzed notification history: {notif.get('total_actions', 0)} total actions")

    settings_folders = list_settings_folders()
    print(f"  {len(settings_folders)} persona settings folders")

    settings_accounts = analyze_settings_accounts_db()
    print(f"  Read accounts.db under each persona")

    # Write summary
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write("# Onimator Farm — Concise Summary for Phantom Fleet Migration\n\n")
        f.write(f"**Installation root:** `{ROOT}`\n\n")
        f.write(f"**Device folders:** {len(devices)}\n\n")
        f.write(f"**Persona settings folders:** {len(settings_folders)}\n\n")
        f.write("---\n\n")

        # Device + account count
        f.write("## Per-device account counts\n\n")
        f.write("| Device | Active accounts | Trashed |\n")
        f.write("|---|---:|---:|\n")
        total_active = 0
        total_trashed = 0
        for dev in devices:
            info = account_map.get(dev, {})
            act = info.get('active_count', 0)
            tr = info.get('trashed_count', 0)
            total_active += act
            total_trashed += tr
            f.write(f"| `{dev}` | {act} | {tr} |\n")
        f.write(f"| **TOTAL** | **{total_active}** | **{total_trashed}** |\n\n")

        # List all active accounts per device
        f.write("### Active account handles per device\n\n")
        for dev in devices:
            info = account_map.get(dev, {})
            accts = info.get('active', [])
            if accts:
                f.write(f"**{dev}** ({len(accts)} accounts):\n")
                for a in accts:
                    f.write(f"- `{a}`\n")
                f.write("\n")

        f.write("\n---\n\n")

        # Persona settings folders
        f.write("## Persona settings folders under `Settings/`\n\n")
        for name in settings_folders:
            f.write(f"- `{name}`\n")
        f.write("\n")

        # Persona accounts.db contents
        f.write("\n## Persona `accounts.db` contents\n\n")
        for persona_name, persona_info in settings_accounts.items():
            f.write(f"### `Settings/{persona_name}/accounts.db`\n\n")
            if 'error' in persona_info or 'note' in persona_info:
                f.write(f"- {persona_info.get('error') or persona_info.get('note')}\n\n")
                continue
            for t, tinfo in persona_info.get('tables', {}).items():
                f.write(f"**Table: `{t}`** — {tinfo.get('count', 0)} rows\n\n")
                cols = tinfo.get('columns', [])
                f.write(f"Columns: `{', '.join(cols)}`\n\n")
                rows = tinfo.get('rows', [])
                if rows:
                    f.write(f"First {min(len(rows), 10)} rows (redacted):\n\n")
                    for row in rows[:10]:
                        parts = []
                        for i, v in enumerate(row):
                            col = cols[i] if i < len(cols) else f'col{i}'
                            parts.append(f"{col}={redact(v, col)}")
                        f.write("- " + ", ".join(parts) + "\n")
                    f.write("\n")
            f.write("\n")

        # Top-level DBs
        f.write("\n---\n\n## Top-level system databases\n\n")
        for db_name, db_info in top_level.items():
            f.write(f"### `{db_name}`\n\n")
            for t, tinfo in db_info.get('tables', {}).items():
                f.write(f"- **{t}** — {tinfo.get('row_count', 0)} rows\n")
                cols = tinfo.get('columns', [])
                if cols:
                    f.write(f"  Columns: `{', '.join(cols)}`\n")
            f.write("\n")

        # Notification history
        if notif:
            f.write("\n---\n\n## Action history (notificationdatabase.db)\n\n")
            f.write(f"- **Total actions logged:** {notif.get('total_actions', 0):,}\n")
            f.write(f"- **Unique accounts with actions:** {notif.get('unique_accounts', 0)}\n")
            f.write(f"- **Unique devices with actions:** {notif.get('unique_devices', 0)}\n\n")

            f.write("### Actions per device\n\n")
            f.write("| Device | Actions | Unique accounts |\n")
            f.write("|---|---:|---:|\n")
            for row in notif.get('per_device', []):
                f.write(f"| `{row[0]}` | {row[1]:,} | {row[2]} |\n")
            f.write("\n")

            f.write("### Top 30 most-active accounts\n\n")
            f.write("| Account | Device | Actions | First | Last |\n")
            f.write("|---|---|---:|---|---|\n")
            for row in notif.get('top_30_accounts', []):
                f.write(f"| `{row[0]}` | `{row[1]}` | {row[2]:,} | {row[3]} | {row[4]} |\n")
            f.write("\n")

            f.write("### Action type frequency\n\n")
            for row in notif.get('action_types', []):
                action_name = str(row[0])[:100] if row[0] else '(null)'
                f.write(f"- `{action_name}`: {row[1]:,}\n")
            f.write("\n")

        # iguserdatabase scraped targets
        iguser = top_level.get('iguserdatabase.db', {})
        if iguser:
            f.write("\n---\n\n## Scraped target pool (`iguserdatabase.db`)\n\n")
            for t, tinfo in iguser.get('tables', {}).items():
                f.write(f"- **{t}** — {tinfo.get('row_count', 0):,} rows (scraped IG users for targeting)\n")
            f.write("\n")

    print(f"\nWrote {OUT}")


if __name__ == '__main__':
    main()
