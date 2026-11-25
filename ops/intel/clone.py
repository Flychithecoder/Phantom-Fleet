"""#2 Behavioral cloning — MLE fits over the Onimator action log.

The Onimator install at C:\\Onimator\\full_igbot_14.1.8.1\\
notificationdatabase.db contains ~43,571 action rows across 72 days
(per HARDWARE.md). That's free, labeled, in-production training data.

This module fits per-account distributions out of it:

  * **inter-action delay** -> LogNormal(mu, sigma)
  * **actions-per-day**    -> Normal(mu, sigma) clipped to 22
  * **diurnal peak hour**  -> circular mean of hour-of-day
  * **burstiness index**   -> variance / mean of inter-arrival (Fano factor)

Writes the fits into the persona_profiles table so new accounts
inheriting a persona get its historical fingerprint instead of a flat
LogNormal(0.0, 0.3) we pulled out of thin air.

Pure stats. No ML. Every fit is MLE on raw timestamps.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402

ONIMATOR_DB = Path(r"C:\Onimator\full_igbot_14.1.8.1\notificationdatabase.db")


@dataclass
class AccountFit:
    account: str
    sample_size: int
    inter_action_mu: float     # LogNormal of inter-arrival seconds
    inter_action_sigma: float
    per_day_mean: float
    per_day_std: float
    peak_hour_local: int        # circular mean [0, 24)
    fano_factor: float          # >1 = bursty, <1 = regular


def _open_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _ts_column(con: sqlite3.Connection, table: str) -> str | None:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info('{table}')")]
    for cand in ("ts_ms", "timestamp", "ts", "time", "created_at", "date"):
        if cand in cols:
            return cand
    return None


def _acct_column(con: sqlite3.Connection, table: str) -> str | None:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info('{table}')")]
    for cand in ("account", "username", "user", "login", "ig_user"):
        if cand in cols:
            return cand
    return None


def extract_pairs(con: sqlite3.Connection) -> dict[str, list[int]]:
    """Return {account: sorted [ts_ms]} across every table in the DB."""
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]
    acc: dict[str, list[int]] = {}
    for t in tables:
        ac = _acct_column(con, t)
        tc = _ts_column(con, t)
        if not ac or not tc:
            continue
        try:
            rows = con.execute(
                f"SELECT \"{ac}\", \"{tc}\" FROM \"{t}\" "
                f"WHERE \"{ac}\" IS NOT NULL AND \"{tc}\" IS NOT NULL"
            ).fetchall()
        except sqlite3.DatabaseError:
            continue
        for a, ts in rows:
            if not a:
                continue
            ms = _coerce_ms(ts)
            if ms is None:
                continue
            acc.setdefault(str(a), []).append(ms)
    for a in acc:
        acc[a].sort()
    return acc


def _coerce_ms(v: Any) -> int | None:
    try:
        if isinstance(v, (int, float)):
            n = int(v)
            if n < 10**10:  # seconds
                return n * 1000
            return n
        s = str(v)
        if s.isdigit():
            return _coerce_ms(int(s))
        return None
    except Exception:
        return None


def fit_account(account: str, ts_list: list[int]) -> AccountFit | None:
    if len(ts_list) < 20:
        return None
    gaps_s = [(b - a) / 1000.0 for a, b in zip(ts_list, ts_list[1:])
              if b > a and (b - a) < 24 * 3600 * 1000]
    if len(gaps_s) < 10:
        return None
    log_gaps = [math.log(g) for g in gaps_s if g > 0]
    mu = statistics.fmean(log_gaps)
    sigma = statistics.pstdev(log_gaps) or 0.3

    # Actions per day
    day_counts: dict[int, int] = {}
    for ts in ts_list:
        day = ts // (24 * 3600 * 1000)
        day_counts[day] = day_counts.get(day, 0) + 1
    daily = list(day_counts.values())
    per_day_mean = statistics.fmean(daily)
    per_day_std = statistics.pstdev(daily) or 1.0

    # Diurnal peak: circular mean of hour-of-day (UTC; caller shifts for tz)
    hours = [(ts // 3600_000) % 24 for ts in ts_list]
    x = statistics.fmean(math.cos(h * math.pi / 12) for h in hours)
    y = statistics.fmean(math.sin(h * math.pi / 12) for h in hours)
    ang = math.atan2(y, x) * 12 / math.pi
    peak = int(round(ang)) % 24

    # Fano factor over 1h buckets
    buckets: dict[int, int] = {}
    for ts in ts_list:
        buckets[ts // 3600_000] = buckets.get(ts // 3600_000, 0) + 1
    vals = list(buckets.values())
    fano = (statistics.pvariance(vals) / statistics.fmean(vals)
            if statistics.fmean(vals) else 1.0)

    return AccountFit(
        account=account, sample_size=len(ts_list),
        inter_action_mu=mu, inter_action_sigma=sigma,
        per_day_mean=per_day_mean, per_day_std=per_day_std,
        peak_hour_local=peak, fano_factor=fano,
    )


def fit_all(source: Path = ONIMATOR_DB) -> list[AccountFit]:
    if not source.exists():
        return []
    con = _open_ro(source)
    try:
        pairs = extract_pairs(con)
    finally:
        con.close()
    out: list[AccountFit] = []
    for a, ts in pairs.items():
        f = fit_account(a, ts)
        if f:
            out.append(f)
    return out


def persist(fits: list[AccountFit]) -> None:
    """Write fits as persona_profiles rows (one per account)."""
    _store.apply_migrations()
    with _store.connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS account_fits (
            account TEXT PRIMARY KEY,
            sample_size INTEGER NOT NULL,
            inter_action_mu REAL NOT NULL,
            inter_action_sigma REAL NOT NULL,
            per_day_mean REAL NOT NULL,
            per_day_std REAL NOT NULL,
            peak_hour_local INTEGER NOT NULL,
            fano_factor REAL NOT NULL,
            fitted_ms INTEGER NOT NULL
        );
        """)
        now = int(time.time() * 1000)
        con.executemany(
            "INSERT OR REPLACE INTO account_fits "
            "(account, sample_size, inter_action_mu, inter_action_sigma, "
            "per_day_mean, per_day_std, peak_hour_local, fano_factor, fitted_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(f.account, f.sample_size, f.inter_action_mu, f.inter_action_sigma,
              f.per_day_mean, f.per_day_std, f.peak_hour_local,
              f.fano_factor, now) for f in fits],
        )


def summary(fits: list[AccountFit]) -> dict:
    if not fits:
        return {"n": 0}
    return {
        "n": len(fits),
        "sample_size_median": int(statistics.median(f.sample_size for f in fits)),
        "inter_action_mu_mean": statistics.fmean(f.inter_action_mu for f in fits),
        "inter_action_sigma_mean": statistics.fmean(f.inter_action_sigma for f in fits),
        "per_day_mean_mean": statistics.fmean(f.per_day_mean for f in fits),
        "peak_hour_spread":
            max(f.peak_hour_local for f in fits)
            - min(f.peak_hour_local for f in fits),
        "fano_median": statistics.median(f.fano_factor for f in fits),
    }
