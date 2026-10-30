"""Concurrency-safe LLM budget management with atomic reservations and usage reconciliation.

Provides pre-allocation reservation accounting to prevent concurrent requests from
bypassing configured spending ceilings.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from foresight.agents.llm import LLMResponse
from foresight.config import ProviderConfig

DISCLAIMER_TEXT = (
    "Client-side pre-allocation reservation limit. Upstream spending caps require "
    "provider-side enforcement."
)


class BudgetExceededError(Exception):
    """Raised when an LLM call or reservation would exceed the configured spending ceiling."""

    def __init__(
        self,
        message: str,
        current_spend: float = 0.0,
        reserved: float = 0.0,
        requested: float = 0.0,
        limit: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.current_spend = current_spend
        self.reserved = reserved
        self.requested = requested
        self.limit = limit


@dataclass
class Reservation:
    reservation_id: str
    session_id: str
    estimated_usd: float
    created_at: float
    provider: str
    committed: bool = False
    released: bool = False
    actual_usd: float | None = None


class BudgetSummary(BaseModel):
    total_budget_usd: float | None = None
    total_spent_usd: float = 0.0
    total_reserved_usd: float = 0.0
    total_remaining_usd: float | None = None
    session_budget_usd: float | None = None
    session_spent_usd: float = 0.0
    session_reserved_usd: float = 0.0
    session_remaining_usd: float | None = None
    active_reservations_count: int = 0
    spending_ceiling_guaranteed: bool = False
    disclaimer: str = DISCLAIMER_TEXT


def estimate_call_cost(
    config: ProviderConfig,
    prompt_input: Any,
    max_output_tokens: int | None = 4000,
) -> float:
    """Conservatively estimate cost (USD) of an LLM call prior to sending."""
    text = str(prompt_input)
    # Conservative token estimation: ~3 chars per token for code/JSON prompts, floor at 500
    est_input = max(500, int(len(text) / 3))
    est_output = max_output_tokens or 4000
    # Assume 0 cached tokens for conservative pre-reservation
    return round(config.cost_usd(est_input, 0, est_output), 6)


def calculate_actual_cost(
    config: ProviderConfig,
    resp: LLMResponse,
    prompt_input: Any,
    max_output_tokens: int | None = 4000,
) -> float:
    """Calculate actual cost with conservative accounting when provider usage metadata is missing."""
    in_tok = resp.input_tokens
    out_tok = resp.output_tokens
    cached_tok = resp.cached_input_tokens
    if in_tok == 0 and out_tok == 0:
        # Provider did not return token usage: apply conservative accounting
        text_in = str(prompt_input)
        in_tok = max(500, int(len(text_in) / 3))
        text_out = resp.output_text or ""
        out_tok = max(int(len(text_out) / 3), 100) if text_out else (max_output_tokens or 1000)
        cached_tok = 0
    return round(config.cost_usd(in_tok, cached_tok, out_tok), 6)


class LLMBudgetManager:
    """Thread-safe and async-safe budget manager with atomic reservations and reconciliation."""

    def __init__(
        self,
        total_budget_usd: float | None = 10.0,
        session_budget_usd: float | None = 1.0,
    ) -> None:
        self.total_budget_usd = total_budget_usd
        self.session_budget_usd = session_budget_usd
        self._lock = asyncio.Lock()
        self._total_spent_usd: float = 0.0
        self._total_reserved_usd: float = 0.0
        self._session_spent_usd: dict[str, float] = defaultdict(float)
        self._session_reserved_usd: dict[str, float] = defaultdict(float)
        self._active_reservations: dict[str, Reservation] = {}

    async def reserve(
        self,
        session_id: str,
        estimated_usd: float,
        provider: str = "meta",
    ) -> Reservation:
        """Atomically reserve estimated cost before a model call.

        Raises:
            BudgetExceededError: If the reservation would exceed total or per-session budget.
        """
        async with self._lock:
            # Check service-level total budget
            if self.total_budget_usd is not None:
                projected_total = self._total_spent_usd + self._total_reserved_usd + estimated_usd
                if projected_total > self.total_budget_usd + 1e-9:
                    raise BudgetExceededError(
                        f"Total LLM budget exceeded: ${self._total_spent_usd:.4f} spent + "
                        f"${self._total_reserved_usd:.4f} reserved + ${estimated_usd:.4f} requested "
                        f"exceeds limit ${self.total_budget_usd:.4f}",
                        current_spend=self._total_spent_usd,
                        reserved=self._total_reserved_usd,
                        requested=estimated_usd,
                        limit=self.total_budget_usd,
                    )

            # Check per-session budget
            if self.session_budget_usd is not None:
                s_spent = self._session_spent_usd[session_id]
                s_res = self._session_reserved_usd[session_id]
                projected_session = s_spent + s_res + estimated_usd
                if projected_session > self.session_budget_usd + 1e-9:
                    raise BudgetExceededError(
                        f"Session '{session_id}' budget exceeded: ${s_spent:.4f} spent + "
                        f"${s_res:.4f} reserved + ${estimated_usd:.4f} requested exceeds "
                        f"limit ${self.session_budget_usd:.4f}",
                        current_spend=s_spent,
                        reserved=s_res,
                        requested=estimated_usd,
                        limit=self.session_budget_usd,
                    )

            res_id = f"res-{uuid.uuid4().hex[:12]}"
            reservation = Reservation(
                reservation_id=res_id,
                session_id=session_id,
                estimated_usd=estimated_usd,
                created_at=time.time(),
                provider=provider,
            )
            self._active_reservations[res_id] = reservation
            self._total_reserved_usd += estimated_usd
            self._session_reserved_usd[session_id] += estimated_usd
            return reservation

    async def reconcile(self, reservation_id: str, actual_usd: float) -> None:
        """Reconcile actual cost upon successful model call completion."""
        async with self._lock:
            res = self._active_reservations.pop(reservation_id, None)
            if res is None or res.committed or res.released:
                return

            res.committed = True
            res.actual_usd = actual_usd
            self._total_reserved_usd = max(0.0, self._total_reserved_usd - res.estimated_usd)
            self._session_reserved_usd[res.session_id] = max(
                0.0, self._session_reserved_usd[res.session_id] - res.estimated_usd
            )
            self._total_spent_usd += actual_usd
            self._session_spent_usd[res.session_id] += actual_usd

    async def release(self, reservation_id: str) -> None:
        """Release unused reservation on model call failure, timeout, or cancellation."""
        async with self._lock:
            res = self._active_reservations.pop(reservation_id, None)
            if res is None or res.committed or res.released:
                return

            res.released = True
            self._total_reserved_usd = max(0.0, self._total_reserved_usd - res.estimated_usd)
            self._session_reserved_usd[res.session_id] = max(
                0.0, self._session_reserved_usd[res.session_id] - res.estimated_usd
            )

    @asynccontextmanager
    async def reservation_context(
        self,
        session_id: str,
        estimated_usd: float,
        provider: str = "meta",
    ) -> AsyncIterator[ReservationController]:
        """Context manager guaranteeing reservation release on any failure or cancellation."""
        reservation = await self.reserve(session_id, estimated_usd, provider=provider)
        ctrl = ReservationController(reservation.reservation_id)
        try:
            yield ctrl
            if ctrl.committed:
                await self.reconcile(reservation.reservation_id, ctrl.actual_usd or 0.0)
            else:
                await self.release(reservation.reservation_id)
        except Exception:
            if not ctrl.committed:
                await self.release(reservation.reservation_id)
            raise

    async def get_summary(self, session_id: str | None = None) -> BudgetSummary:
        """Get aggregate and per-session budget metrics."""
        async with self._lock:
            total_rem = (
                max(0.0, self.total_budget_usd - (self._total_spent_usd + self._total_reserved_usd))
                if self.total_budget_usd is not None
                else None
            )

            s_spent = self._session_spent_usd.get(session_id, 0.0) if session_id else 0.0
            s_res = self._session_reserved_usd.get(session_id, 0.0) if session_id else 0.0
            session_rem = (
                max(0.0, self.session_budget_usd - (s_spent + s_res))
                if self.session_budget_usd is not None and session_id
                else None
            )

            return BudgetSummary(
                total_budget_usd=self.total_budget_usd,
                total_spent_usd=round(self._total_spent_usd, 6),
                total_reserved_usd=round(self._total_reserved_usd, 6),
                total_remaining_usd=round(total_rem, 6) if total_rem is not None else None,
                session_budget_usd=self.session_budget_usd,
                session_spent_usd=round(s_spent, 6),
                session_reserved_usd=round(s_res, 6),
                session_remaining_usd=round(session_rem, 6) if session_rem is not None else None,
                active_reservations_count=len(self._active_reservations),
                spending_ceiling_guaranteed=False,
                disclaimer=DISCLAIMER_TEXT,
            )

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up reservations and release any outstanding holds when a session is deleted."""
        async with self._lock:
            to_remove = [
                rid for rid, r in self._active_reservations.items() if r.session_id == session_id
            ]
            for rid in to_remove:
                res = self._active_reservations.pop(rid)
                self._total_reserved_usd = max(0.0, self._total_reserved_usd - res.estimated_usd)
            self._session_reserved_usd.pop(session_id, None)
            self._session_spent_usd.pop(session_id, None)


class ReservationController:
    """Helper provided to context manager callers to signal successful completion and actual cost."""

    def __init__(self, reservation_id: str) -> None:
        self.reservation_id = reservation_id
        self.committed = False
        self.actual_usd: float | None = None

    def commit(self, actual_usd: float) -> None:
        self.committed = True
        self.actual_usd = actual_usd
