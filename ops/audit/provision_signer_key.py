"""Mint PF_AUDIT_SIGNER_KEY — one-shot provisioning.

The weekly commitment (ops/intel/chain.py::make_commitment) HMAC-signs
the chain head with this key. Without a stable, owner-held key, the
commitment is unverifiable, so chain.make_commitment refuses to run
without it.

This script:

  1. Checks if `PF_AUDIT_SIGNER_KEY` is already set in the environment —
     if so, prints its fingerprint and exits 0. Nothing to do.
  2. Checks if a key file already exists at the chosen path — if so,
     refuses to overwrite (safety). Use --force to replace.
  3. Otherwise mints 32 bytes via secrets.token_hex and writes them in
     a `.env`-style line to the chosen path. Prints the key once to
     stdout so the owner can save it in a password manager.

The key is a shared secret in Phase 0 (HMAC-SHA256). The owner is the
only party that needs it; auditors receive the key separately out of
band when they verify a commitment.

Usage:

    python ops/audit/provision_signer_key.py
    python ops/audit/provision_signer_key.py --path /path/to/.env.audit
    python ops/audit/provision_signer_key.py --force
    python ops/audit/provision_signer_key.py --print-only

The default path is `backend/.data/.env.audit` so the key sits next to
persona-store.sqlite under the same ownership. Add it to the cron
environment via `env -i $(cat backend/.data/.env.audit) python -m
ops.cron.supervisor ...` or source it before launching the supervisor.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import stat
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _REPO / "backend" / ".data" / ".env.audit"


def _fingerprint(key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(key_hex)).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=_DEFAULT_PATH,
                    help=f"output .env file (default: {_DEFAULT_PATH})")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing key file")
    ap.add_argument("--print-only", action="store_true",
                    help="mint and print to stdout; do not write any file")
    args = ap.parse_args()

    existing_env = os.environ.get("PF_AUDIT_SIGNER_KEY")
    if existing_env and not args.force:
        try:
            fp = _fingerprint(existing_env)
            print(f"PF_AUDIT_SIGNER_KEY already set in env (fingerprint {fp}).")
            print("Nothing to do. Use --force to mint a new one anyway.")
            return 0
        except ValueError:
            print("PF_AUDIT_SIGNER_KEY is set but is not valid hex. Replace it.",
                  file=sys.stderr)
            return 2

    key_hex = secrets.token_hex(32)
    fp = _fingerprint(key_hex)

    if args.print_only:
        print(f"PF_AUDIT_SIGNER_KEY={key_hex}")
        print(f"# fingerprint: {fp}", file=sys.stderr)
        return 0

    if args.path.exists() and not args.force:
        print(f"Refusing to overwrite existing {args.path}. Use --force "
              "if you really want to rotate the key (old commitments then "
              "become unverifiable without the old key).", file=sys.stderr)
        return 3

    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(
        f"# Phantom Fleet audit signer key. DO NOT COMMIT.\n"
        f"# fingerprint: {fp}\n"
        f"PF_AUDIT_SIGNER_KEY={key_hex}\n",
        encoding="utf-8",
    )
    # Best-effort 0600 (owner read/write only). No-op on Windows; the
    # file still sits inside the user's profile so NTFS ACLs apply.
    try:
        os.chmod(args.path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass

    print(f"Wrote {args.path}")
    print(f"fingerprint: {fp}")
    print()
    print("Source this file before running the cron supervisor, e.g.:")
    print(f"  set -a && . {args.path} && set +a")
    print("or on PowerShell:")
    print(f"  Get-Content {args.path} | ForEach-Object {{ if ($_ -match ")
    print(r"    '^PF_AUDIT_SIGNER_KEY=(.+)$') { $env:PF_AUDIT_SIGNER_KEY = $Matches[1] } }")
    print()
    print("Save the key in a password manager too. If you lose it,")
    print("every past commitment becomes unverifiable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
