"""Agent API: run one pass of the operations loop and see what it did.

`POST /agent/run` is what the demo console's "run agent" button calls and what
a scheduler would call every tick in a deployment. It is idempotent in the
sense that matters: running it twice on an unchanged network does not open two
incidents or dispatch two crews — the loop reads the current state first and
does the next right thing, which is often nothing.

The response carries the trace because "what did the agent do and why" is the
question this whole product exists to answer.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import AgentDep, RepositoryDep
from app.schemas.detection import Classification
from app.schemas.workorder import DecisionEntry, VerificationReport, WorkOrder

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunResponse(BaseModel):
    """One pass of observe -> ... -> remember."""

    ran_at: datetime
    #: Node-by-node account of the pass, in order.
    trace: list[dict] = Field(default_factory=list)
    classification: Classification | None = None
    work_order: WorkOrder | None = None
    verification: VerificationReport | None = None
    #: The message that would go out over Telegram, if one was written.
    message: str | None = None
    #: Set when the agent stopped and is waiting on a human.
    halted: str | None = None

    @property
    def awaiting_human(self) -> bool:
        return self.halted is not None


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(agent: AgentDep, now: datetime | None = None) -> AgentRunResponse:
    """Advance the incident loop by one pass."""
    try:
        state = await agent.run(now=now)
    except Exception as error:  # noqa: BLE001 -- surfaced, not swallowed
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"agent pass failed: {error}",
        ) from error

    return AgentRunResponse(
        ran_at=state["now"],
        trace=state.get("trace", []),
        classification=state.get("classification"),
        work_order=state.get("work_order"),
        verification=state.get("verification"),
        message=state.get("message"),
        halted=state.get("halted"),
    )


@router.get("/decisions", response_model=list[DecisionEntry])
async def list_decisions(
    repository: RepositoryDep,
    work_order_id: str | None = None,
    fault_event_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DecisionEntry]:
    """The decision ledger. Why anything happened, in the agent's own record."""
    return await repository.list_decisions(
        work_order_id=work_order_id, fault_event_id=fault_event_id, limit=limit
    )
