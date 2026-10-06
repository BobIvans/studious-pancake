"""Explicit platform proxy/trust bootstrap for the existing verified transport."""

from contextlib import asynccontextmanager
from dataclasses import replace
from collections.abc import Mapping
import os

import httpx
from src.routing.transport import HttpxJsonTransport, TransportPolicy, build_tls_context


@asynccontextmanager
async def campaign_transport(
    hosts, *, policy=None, environment: Mapping[str, str] | None = None
):
    environment = dict(os.environ) if environment is None else environment
    policy = policy or TransportPolicy(max_attempts=1)
    if policy.max_attempts != 1:
        raise ValueError(
            "campaign records one envelope per physical attempt; automatic retry disabled"
        )
    if policy.ca_bundle_path is None and environment.get("SSL_CERT_FILE"):
        policy = replace(policy, ca_bundle_path=environment["SSL_CERT_FILE"])
    context, _ = build_tls_context(policy)
    timeout = httpx.Timeout(
        connect=policy.connect_timeout_seconds,
        read=policy.read_timeout_seconds,
        write=policy.write_timeout_seconds,
        pool=policy.pool_timeout_seconds,
    )
    async with httpx.AsyncClient(
        proxy=environment.get("HTTPS_PROXY"),
        verify=context,
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
        headers={"Accept-Encoding": "gzip,deflate,identity"},
    ) as client:
        async with HttpxJsonTransport(
            policy=policy, allowed_hosts=frozenset(hosts), client=client
        ) as transport:
            yield transport
