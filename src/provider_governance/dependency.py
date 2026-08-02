"""Deterministic degraded-mode controller for provider dependencies."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import time
from typing import Callable

from .models import (
    AdmissionCode,
    DependencyFailureKind,
    DependencyMode,
    DependencySnapshot,
    ProviderAdmissionError,
    ProviderOperation,
)


def _provider_failure_reason(reason: str) -> str | None:
    raw = reason.rsplit(":", 1)[-1]
    return {
        "rate_limited": "rate_limited",
        "quota": "rate_limited",
        "circuit_open": "circuit_open",
        "timeout": "timeout",
        "transport": "transport",
        "invalid_schema": "invalid_schema",
        "disabled": "disabled",
        "auth": "disabled",
    }.get(raw)


class DependencyController:
    """Own provider degraded/cooldown/disabled transitions.

    Degraded providers may still serve discovery, backfill and health probes, but
    refinement/finalization remain fail-closed until a successful generation-
    bound health probe recovers the dependency. Ordinary discovery success does
    not silently re-enable dangerous operations.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        transient_failure_threshold: int = 2,
        cooldown_seconds: float = 30.0,
    ) -> None:
        if transient_failure_threshold <= 0:
            raise ValueError("transient_failure_threshold must be positive")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self.clock = clock
        self.transient_failure_threshold = transient_failure_threshold
        self.cooldown_seconds = float(cooldown_seconds)
        self._states: dict[str, DependencySnapshot] = {}
        self._lock = asyncio.Lock()

    def _initial(self, provider_id: str, generation: str) -> DependencySnapshot:
        return DependencySnapshot(
            provider_id=provider_id,
            generation=generation,
            mode=DependencyMode.ACTIVE,
            consecutive_failures=0,
            reason="entitlement_generation_active",
            retry_at=None,
        )

    def peek(self, provider_id: str, generation: str) -> DependencySnapshot:
        state = self._states.get(provider_id)
        if state is None or state.generation != generation:
            return self._initial(provider_id, generation)
        return state

    def _state_for_generation(
        self, provider_id: str, generation: str
    ) -> DependencySnapshot:
        state = self._states.get(provider_id)
        if state is None or state.generation != generation:
            state = self._initial(provider_id, generation)
            self._states[provider_id] = state
        return state

    async def assert_admissible(
        self,
        provider_id: str,
        generation: str,
        operation: ProviderOperation,
    ) -> None:
        async with self._lock:
            now = self.clock()
            state = self._state_for_generation(provider_id, generation)
            if (
                state.mode is DependencyMode.COOLDOWN
                and state.retry_at is not None
                and now >= state.retry_at
            ):
                state = replace(
                    state,
                    mode=DependencyMode.DEGRADED,
                    reason="cooldown_elapsed_probe_required",
                    retry_at=None,
                )
                self._states[provider_id] = state

            if state.mode is DependencyMode.DISABLED:
                if operation is ProviderOperation.HEALTH_PROBE:
                    return
                raise ProviderAdmissionError(
                    provider_id,
                    AdmissionCode.DEPENDENCY_DISABLED,
                    state.reason,
                    retryable=False,
                    failure_reason=_provider_failure_reason(state.reason),
                )
            if state.mode is DependencyMode.COOLDOWN:
                if operation is ProviderOperation.HEALTH_PROBE:
                    return
                raise ProviderAdmissionError(
                    provider_id,
                    AdmissionCode.DEPENDENCY_COOLDOWN,
                    state.reason,
                    retryable=True,
                    retry_at=state.retry_at,
                    failure_reason=_provider_failure_reason(state.reason),
                )
            if state.mode is DependencyMode.DEGRADED and operation in {
                ProviderOperation.REFINEMENT,
                ProviderOperation.FINALIZATION,
            }:
                raise ProviderAdmissionError(
                    provider_id,
                    AdmissionCode.DEGRADED_OPERATION_DENIED,
                    state.reason,
                    retryable=True,
                    failure_reason=_provider_failure_reason(state.reason),
                )

    async def record_success(
        self,
        provider_id: str,
        generation: str,
        operation: ProviderOperation = ProviderOperation.DISCOVERY,
    ) -> None:
        """Record success without bypassing probe-required recovery.

        A health probe may restore the current generation. A normal operation
        resets counters only while the dependency is already active; discovery
        or backfill success in degraded mode does not re-enable refinement or
        finalization.
        """

        async with self._lock:
            state = self._state_for_generation(provider_id, generation)
            if operation is ProviderOperation.HEALTH_PROBE:
                self._states[provider_id] = DependencySnapshot(
                    provider_id=provider_id,
                    generation=generation,
                    mode=DependencyMode.ACTIVE,
                    consecutive_failures=0,
                    reason="generation_bound_probe_succeeded",
                    retry_at=None,
                )
                return
            if state.mode is DependencyMode.ACTIVE:
                self._states[provider_id] = replace(
                    state,
                    consecutive_failures=0,
                    reason=f"operation_succeeded:{operation.value}",
                    retry_at=None,
                )

    async def record_failure(
        self,
        provider_id: str,
        generation: str,
        kind: DependencyFailureKind,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        async with self._lock:
            state = self._state_for_generation(provider_id, generation)
            if kind is DependencyFailureKind.CANCELLED:
                return
            failures = state.consecutive_failures + 1
            if kind in {
                DependencyFailureKind.DISABLED,
                DependencyFailureKind.AUTH,
                DependencyFailureKind.INVALID_SCHEMA,
            }:
                self._states[provider_id] = replace(
                    state,
                    mode=DependencyMode.DISABLED,
                    consecutive_failures=failures,
                    reason=f"hard_failure:{kind.value}",
                    retry_at=None,
                )
                return
            if kind in {
                DependencyFailureKind.RATE_LIMITED,
                DependencyFailureKind.QUOTA,
                DependencyFailureKind.CIRCUIT_OPEN,
            }:
                delay = (
                    self.cooldown_seconds
                    if retry_after_seconds is None
                    else max(self.cooldown_seconds, float(retry_after_seconds))
                )
                self._states[provider_id] = replace(
                    state,
                    mode=DependencyMode.COOLDOWN,
                    consecutive_failures=failures,
                    reason=f"cooldown:{kind.value}",
                    retry_at=self.clock() + delay,
                )
                return
            if kind in {
                DependencyFailureKind.TIMEOUT,
                DependencyFailureKind.TRANSPORT,
                DependencyFailureKind.UNKNOWN,
            }:
                if failures >= self.transient_failure_threshold:
                    self._states[provider_id] = replace(
                        state,
                        mode=DependencyMode.COOLDOWN,
                        consecutive_failures=failures,
                        reason=f"transient_threshold:{kind.value}",
                        retry_at=self.clock() + self.cooldown_seconds,
                    )
                else:
                    self._states[provider_id] = replace(
                        state,
                        mode=DependencyMode.DEGRADED,
                        consecutive_failures=failures,
                        reason=f"transient_failure:{kind.value}",
                        retry_at=None,
                    )
                return
            self._states[provider_id] = replace(
                state,
                mode=DependencyMode.DEGRADED,
                consecutive_failures=failures,
                reason=f"unclassified_failure:{kind.value}",
                retry_at=None,
            )

    async def snapshot(self, provider_id: str, generation: str) -> DependencySnapshot:
        async with self._lock:
            state = self._state_for_generation(provider_id, generation)
            if (
                state.mode is DependencyMode.COOLDOWN
                and state.retry_at is not None
                and self.clock() >= state.retry_at
            ):
                state = replace(
                    state,
                    mode=DependencyMode.DEGRADED,
                    reason="cooldown_elapsed_probe_required",
                    retry_at=None,
                )
                self._states[provider_id] = state
            return state


__all__ = ["DependencyController"]
