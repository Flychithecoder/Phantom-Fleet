"""#5 Merkle audit chain — tamper-evident, replayable, auditor-friendly.

Every deterministic decision (scheduler tick, recovery transition,
proxy rotate, safety critique) hashes into a running chain:

    H_n = SHA-256( H_{n-1} || canonical_json(record) )

The owner signs the chain head weekly. Anyone with the chain file +
the weekly signatures can re-derive every head and prove the system
performed exactly those decisions and no others.

Phase 1 extension (stubbed by a clean interface here, not built): swap
the signer for a zk-STARK prover so a tenant can prove policy
compliance without disclosing the record contents. The chain shape is
identical; only `make_commitment()` changes.

Pure stdlib (hashlib + hmac + ed25519-ish fallback to HMAC-SHA256 so
the module has no non-stdlib deps). Deterministic.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ops.sched import _store  # noqa: E402

CHAIN_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS audit_chain (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        record_hash TEXT NOT NULL,     -- hash of the record alone
        prev_head TEXT NOT NULL,       -- chain head before this record
        head TEXT NOT NULL,            -- chain head after this record
        record_json TEXT NOT NULL,
        ts_ms INTEGER NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_audit_chain_ts ON audit_chain(ts_ms);",
    """
    CREATE TABLE IF NOT EXISTS audit_commitments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_start_ms INTEGER NOT NULL,
        head TEXT NOT NULL,            -- chain head at commitment
        signature_hex TEXT NOT NULL,   -- HMAC-SHA256 (Phase 1: zk-STARK)
        signer_fingerprint TEXT NOT NULL,
        created_ms INTEGER NOT NULL
    );
    """,
]

GENESIS = "0" * 64


def _init() -> None:
    _store.apply_migrations()
    with _store.connect() as con:
        for stmt in CHAIN_SCHEMA:
            con.executescript(stmt)


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, default=str,
                      separators=(",", ":")).encode("utf-8")


def _hash(prev_head: str, record: Any) -> tuple[str, str]:
    rec_h = hashlib.sha256(_canonical(record)).hexdigest()
    head = hashlib.sha256(
        bytes.fromhex(prev_head) + bytes.fromhex(rec_h)
    ).hexdigest()
    return rec_h, head


def current_head() -> str:
    _init()
    with _store.connect() as con:
        row = con.execute(
            "SELECT head FROM audit_chain ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["head"] if row else GENESIS


def append(kind: str, record: dict) -> dict:
    """Append one decision to the chain. Returns {id, head}."""
    _init()
    prev = current_head()
    rec_h, head = _hash(prev, record)
    with _store.connect() as con:
        cur = con.execute(
            "INSERT INTO audit_chain "
            "(kind, record_hash, prev_head, head, record_json, ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kind, rec_h, prev, head, _canonical(record).decode("utf-8"),
             int(time.time() * 1000)),
        )
    return {"id": int(cur.lastrowid or 0), "record_hash": rec_h, "head": head}


def verify_chain() -> dict:
    """Walk the chain from the start, recompute every head, flag any
    row whose stored head doesn't match the recomputed one.

    This is what an auditor runs. An hour of fleet ops produces
    ~thousands of rows; full verify is O(n) with one hash per row.
    """
    _init()
    bad: list[dict] = []
    prev = GENESIS
    rows_seen = 0
    with _store.connect() as con:
        for row in con.execute(
            "SELECT id, record_json, head, prev_head FROM audit_chain "
            "ORDER BY id"
        ):
            rows_seen += 1
            rec = json.loads(row["record_json"])
            _, computed_head = _hash(prev, rec)
            if row["prev_head"] != prev or row["head"] != computed_head:
                bad.append({"id": row["id"], "expected_head": computed_head,
                            "stored_head": row["head"]})
            prev = row["head"]
    return {"rows": rows_seen, "tampered": bad, "ok": not bad, "head": prev}


def make_commitment(signer_key_hex: str | None = None) -> dict:
    """Produce a weekly commitment: the chain head + a signature.

    Phase 0 signer: HMAC-SHA256 over the head, keyed by the owner's
    local secret (env `PF_AUDIT_SIGNER_KEY` or passed in). Phase 1
    swaps HMAC for a zk-STARK proof over the policy predicate
    "every recorded decision satisfies rules R1..Rn" — the chain
    shape here is the input that proof commits to.
    """
    _init()
    key_hex = signer_key_hex or os.environ.get("PF_AUDIT_SIGNER_KEY")
    if not key_hex:
        # Refuse: a weekly commitment is pointless without a stable key
        # the owner can later use to verify. Mint one with
        # `python ops/audit/provision_signer_key.py` and export it in
        # the cron environment.
        raise RuntimeError(
            "PF_AUDIT_SIGNER_KEY is not set. Run "
            "`python ops/audit/provision_signer_key.py` to mint one, "
            "save the output, and export it before calling make_commitment."
        )
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise RuntimeError(
            "PF_AUDIT_SIGNER_KEY must be 64 hex chars (32 bytes). "
            f"Got {len(key_hex)} chars that failed hex decode."
        ) from exc
    if len(key) != 32:
        raise RuntimeError(
            f"PF_AUDIT_SIGNER_KEY must decode to 32 bytes; got {len(key)}."
        )
    head = current_head()
    sig = hmac.new(key, head.encode("ascii"), hashlib.sha256).hexdigest()
    fp = hashlib.sha256(key).hexdigest()[:16]
    week_start = int(time.time() * 1000) // (7 * 86400 * 1000) * (7 * 86400 * 1000)
    with _store.connect() as con:
        cur = con.execute(
            "INSERT INTO audit_commitments "
            "(week_start_ms, head, signature_hex, signer_fingerprint, created_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (week_start, head, sig, fp, int(time.time() * 1000)),
        )
    return {
        "commitment_id": int(cur.lastrowid or 0),
        "head": head, "signature_hex": sig,
        "signer_fingerprint": fp, "week_start_ms": week_start,
    }


def verify_commitment(commitment_id: int, signer_key_hex: str) -> dict:
    """Independent check: given the owner's public verification key
    (symmetric for Phase 0; this becomes a true public key under
    zk-STARKs), confirm the stored signature is valid for the stored
    head. Does NOT re-walk the chain — call `verify_chain()` for that.
    """
    _init()
    with _store.connect() as con:
        row = con.execute(
            "SELECT * FROM audit_commitments WHERE id = ?", (commitment_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "no_such_commitment"}
    expected = hmac.new(
        bytes.fromhex(signer_key_hex),
        row["head"].encode("ascii"), hashlib.sha256,
    ).hexdigest()
    return {
        "ok": hmac.compare_digest(expected, row["signature_hex"]),
        "head": row["head"], "signer_fingerprint": row["signer_fingerprint"],
        "week_start_ms": row["week_start_ms"],
    }
