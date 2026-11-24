"""
Proxy pool management — provider-agnostic.

Endpoints:
    GET    /api/proxy/pool             — list all configured proxies
    POST   /api/proxy/pool             — add one or many proxy lines
    DELETE /api/proxy/pool/{index}     — remove the entry at that index
    POST   /api/proxy/pool/verify      — probe every entry, return per-entry IP

The pool held on app.state.proxy may be any ISPProxyPool subclass. Mutations
require it to be a GenericProxyPool (vendor-specific pools stay read-only).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...proxy import GenericProxyPool, ISPProxyPool, _parse_proxy_line

log = logging.getLogger("phantom_fleet.api.proxy_pool")
router = APIRouter()


class ProxyRow(BaseModel):
    index: int
    host: str
    port: int
    username: str
    has_password: bool


class ProxyListOut(BaseModel):
    pool_size: int
    mutable: bool
    accounts_per_ip: int
    groups_per_phone: int
    proxies: list[ProxyRow]


class AddProxiesIn(BaseModel):
    lines: list[str]


class AddProxiesOut(BaseModel):
    added: int
    pool_size: int
    errors: list[str]


class VerifyRow(BaseModel):
    index: int
    host: str
    port: int
    ok: bool
    external_ip: str | None = None
    error: str | None = None


class VerifyPoolOut(BaseModel):
    pool_size: int
    ok_count: int
    results: list[VerifyRow]


def _pool(request: Request) -> ISPProxyPool:
    p = getattr(request.app.state, "proxy", None)
    if not isinstance(p, ISPProxyPool):
        raise HTTPException(status_code=409,
                            detail="No ISPProxyPool attached to app.state.proxy.")
    return p


@router.get("/pool", response_model=ProxyListOut)
async def list_pool(request: Request) -> ProxyListOut:
    pool = _pool(request)
    rows = pool.list_proxies() if hasattr(pool, "list_proxies") else [
        {"index": i, "host": p.host, "port": p.port,
         "username": p.username, "has_password": bool(p.password)}
        for i, p in enumerate(pool._pool)
    ]
    return ProxyListOut(
        pool_size=len(pool._pool),
        mutable=isinstance(pool, GenericProxyPool),
        accounts_per_ip=pool.accounts_per_ip,
        groups_per_phone=pool.groups_per_phone,
        proxies=[ProxyRow(**r) for r in rows],
    )


@router.post("/pool", response_model=AddProxiesOut)
async def add_proxies(body: AddProxiesIn, request: Request) -> AddProxiesOut:
    pool = _pool(request)
    if not isinstance(pool, GenericProxyPool):
        raise HTTPException(status_code=409,
                            detail="Active pool is vendor-specific and read-only. "
                                   "Switch to a GenericProxyPool (set PHANTOM_PROXY_POOL, "
                                   "or unset vendor env vars) before mutating.")
    added = 0
    errors: list[str] = []
    for raw in body.lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            pool.add_proxy(line)
            added += 1
        except Exception as exc:
            errors.append(f"{line!r}: {exc}")
    return AddProxiesOut(added=added, pool_size=len(pool._pool), errors=errors)


@router.delete("/pool/{index}")
async def remove_proxy(index: int, request: Request) -> dict:
    pool = _pool(request)
    if not isinstance(pool, GenericProxyPool):
        raise HTTPException(status_code=409,
                            detail="Active pool is read-only.")
    try:
        removed = pool.remove_proxy(index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "removed": {"host": removed.host, "port": removed.port},
        "pool_size": len(pool._pool),
    }


@router.post("/pool/verify", response_model=VerifyPoolOut)
async def verify_pool(request: Request) -> VerifyPoolOut:
    import httpx
    pool = _pool(request)

    async def _probe(entry):
        url = entry.url(scheme="http")
        try:
            async with httpx.AsyncClient(proxy=url, timeout=10) as client:
                resp = await client.get("https://checkip.amazonaws.com")
                resp.raise_for_status()
                return resp.text.strip(), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    probes = await asyncio.gather(*[_probe(p) for p in pool._pool],
                                  return_exceptions=False)
    rows: list[VerifyRow] = []
    ok_count = 0
    for i, (p, (ip, err)) in enumerate(zip(pool._pool, probes)):
        ok = ip is not None
        if ok:
            ok_count += 1
        rows.append(VerifyRow(index=i, host=p.host, port=p.port,
                              ok=ok, external_ip=ip, error=err))
    return VerifyPoolOut(pool_size=len(pool._pool), ok_count=ok_count, results=rows)
