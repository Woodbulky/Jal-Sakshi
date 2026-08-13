"""The agent's tool boundary, and the reasoner behind it.

Most of these assert the *absence* of something. That is the point: the safety
of this system comes from what the agent cannot reach, so the tests have to
check the shape of the surface and not only that the surface works.
"""

from __future__ import annotations

import pytest

from app.agent.llm import (
    OpenAICompatibleReasoner,
    StubReasoner,
    build_reasoner,
)
from app.agent.tools import TOOL_NAMES, AgentTools, ToolError
from app.core.config import Settings
from app.schemas.simulation import FaultType
from app.schemas.workorder import CrewRole
from app.services.memory_repository import InMemoryRepository

pytestmark = pytest.mark.asyncio


# -- the boundary -----------------------------------------------------------
async def test_there_is_no_tool_that_closes_a_work_order(tools: AgentTools) -> None:
    """A model cannot reach for a verb that does not exist."""
    assert not any("close" in name for name in TOOL_NAMES)
    assert not hasattr(tools, "close_work_order")


async def test_there_is_no_tool_that_reads_the_ground_truth(
    tools: AgentTools,
) -> None:
    """`fault_injections` is the simulator's answer key."""
    public = {name for name in dir(tools) if not name.startswith("_")}
    assert not any("injection" in name for name in public)
    assert not any("fault_injection" in name for name in TOOL_NAMES)


async def test_there_is_no_tool_that_runs_arbitrary_sql(tools: AgentTools) -> None:
    public = {name for name in dir(tools) if not name.startswith("_")}
    for forbidden in ("sql", "query", "execute", "raw"):
        assert not any(forbidden in name for name in public), forbidden


async def test_the_agent_cannot_approve_its_own_spending(tools: AgentTools) -> None:
    """It may *ask*. Granting is a human act, so there is no method for it."""
    assert hasattr(tools, "request_approval")
    assert not hasattr(tools, "grant_approval")
    assert not hasattr(tools, "approve_work_order")


async def test_every_advertised_tool_actually_exists(tools: AgentTools) -> None:
    """The allowlist is documentation only if it matches the class."""
    for name in TOOL_NAMES:
        assert hasattr(tools, name), name


# -- resources --------------------------------------------------------------
async def test_the_roster_answers_with_a_role_not_a_guess(tools: AgentTools) -> None:
    member = tools.find_crew(FaultType.POWER_OUTAGE)

    assert member is not None
    assert member.role is CrewRole.ELECTRICIAN


async def test_budget_says_why_not_just_no(tools: AgentTools) -> None:
    """'Refused' without a reason cannot be acted on by a committee."""
    small = await tools.check_budget(500.0)
    assert small["allowed"] is True
    assert small["reason"] is None

    large = await tools.check_budget(50_000.0)
    assert large["allowed"] is False
    assert large["requires_approval"] is True
    assert "limit" in large["reason"] or "budget" in large["reason"]


async def test_missing_spares_are_named_before_the_crew_leaves(
    tools: AgentTools,
) -> None:
    """Vitpur's store has no 5HP starter, which a power fault needs."""
    outage = tools.check_spares(FaultType.POWER_OUTAGE)

    assert outage["ready"] is False
    assert "SP-STRT-5HP" in outage["missing"]
    assert "procurement" in outage["note"]


async def test_a_repair_needing_nothing_is_ready(tools: AgentTools) -> None:
    valve = tools.check_spares(FaultType.VALVE_CLOSURE)

    assert valve["ready"] is True
    assert valve["missing"] == []


async def test_an_unknown_reference_is_a_handled_refusal(tools: AgentTools) -> None:
    with pytest.raises(ToolError, match="no asset"):
        await tools.get_asset("NOT-AN-ASSET")
    with pytest.raises(ToolError, match="no work order"):
        await tools.assign_work_order("WO-999")


async def test_the_ledger_can_be_written_and_read_back(
    tools: AgentTools, repository: InMemoryRepository
) -> None:
    await tools.record_decision(
        decision={"considered": "waiting for daylight"},
        notes="crew cannot safely reach the valve at night",
        tool_called="record_decision",
    )

    entries = await tools.get_decisions()
    assert entries[0].decision["considered"] == "waiting for daylight"
    assert entries[0].actor == "AGENT"
    assert entries[0].agent_role


# -- the reasoner -----------------------------------------------------------
async def test_the_stub_writes_a_usable_field_message() -> None:
    message = await StubReasoner().narrate(
        {
            "fault_type": "VALVE_CLOSURE",
            "asset_code": "VLV-01",
            "households_affected": 212,
            "action_summary": "Inspect and open valve VLV-01.",
            "sla_hours": 8.0,
        }
    )

    assert "VLV-01" in message
    assert "212" in message
    assert "8 hours" in message


async def test_the_stub_does_not_invent_a_cause_it_was_not_given() -> None:
    """UNKNOWN must read as unknown, not as a confident guess."""
    message = await StubReasoner().narrate(
        {"fault_type": "UNKNOWN", "asset_code": "PMP-01"}
    )

    assert "not yet known" in message


async def test_a_sensor_fault_message_tells_the_crew_not_to_operate() -> None:
    message = await StubReasoner().narrate(
        {
            "fault_type": "SENSOR_FAULT",
            "asset_code": "ZONE-A",
            "sensor_health_blocked": True,
            "action_summary": "Service the instrument.",
        }
    )

    assert "supplying" in message
    assert "sensor" in message


def test_an_unconfigured_provider_falls_back_to_the_stub() -> None:
    """The demo must run with no API key and lose nothing but phrasing."""
    settings = Settings(app_env="local", llm_provider="none", llm_api_key="")

    assert isinstance(build_reasoner(settings), StubReasoner)


def test_a_configured_provider_is_selected() -> None:
    settings = Settings(
        app_env="local", llm_provider="groq", llm_api_key="test-key"
    )
    reasoner = build_reasoner(settings)

    assert isinstance(reasoner, OpenAICompatibleReasoner)
    assert "groq" in reasoner.name


def test_a_provider_without_an_adapter_degrades_rather_than_crashing() -> None:
    # `llm_base_url` is pinned empty so a developer's .env cannot decide which
    # branch this takes.
    settings = Settings(
        app_env="local",
        llm_provider="anthropic",
        llm_api_key="test-key",
        llm_base_url="",
    )

    assert isinstance(build_reasoner(settings), StubReasoner)


async def test_a_failing_endpoint_still_produces_a_message() -> None:
    """An inference outage must not stop a crew being dispatched."""
    settings = Settings(
        app_env="local",
        llm_provider="groq",
        llm_api_key="test-key",
        llm_base_url="http://127.0.0.1:9",  # nothing listens here
        llm_timeout_seconds=0.5,
    )
    reasoner = OpenAICompatibleReasoner(settings)

    message = await reasoner.narrate(
        {
            "fault_type": "VALVE_CLOSURE",
            "asset_code": "VLV-01",
            "action_summary": "Open the valve.",
        }
    )

    assert "VLV-01" in message
