"""Vitpur's crew roster, stores, and committee account.

Deliberately not database tables. A village of 380 households has seven people
who might be sent out and a cupboard of spares; modelling that as a workforce
management system would be architecture for its own sake. The roster is demo
configuration, and `DATA_MODEL.md` lists no crew table.

`vwsc_accounts` *is* a table, because money has to be auditable — this module
only supplies the seed row.

Names and numbers are fictional, like Vitpur itself.
"""

from __future__ import annotations

from app.schemas.simulation import FaultType
from app.schemas.workorder import CrewMember, CrewRole, SparePart, VwscAccount

FISCAL_YEAR = "2026-27"

ROSTER: tuple[CrewMember, ...] = (
    CrewMember(
        name="Ramesh Yadav",
        role=CrewRole.VALVE_OPERATOR,
        phone="+91-90000-00001",
        telegram_chat_id="demo-valve-operator",
        skills=[FaultType.VALVE_CLOSURE],
    ),
    CrewMember(
        name="Sunil Kumar",
        role=CrewRole.PUMP_OPERATOR,
        phone="+91-90000-00002",
        telegram_chat_id="demo-pump-operator",
        skills=[FaultType.PUMP_FAILURE],
    ),
    CrewMember(
        name="Imran Sheikh",
        role=CrewRole.ELECTRICIAN,
        phone="+91-90000-00003",
        telegram_chat_id="demo-electrician",
        skills=[FaultType.POWER_OUTAGE, FaultType.PUMP_FAILURE],
    ),
    CrewMember(
        name="Dinesh Patel",
        role=CrewRole.LINEMAN,
        phone="+91-90000-00004",
        telegram_chat_id="demo-lineman",
        skills=[
            FaultType.PIPELINE_BURST,
            FaultType.THEFT_OR_UNAUTHORISED_TAPPING,
        ],
    ),
    CrewMember(
        name="Anita Devi",
        role=CrewRole.INSTRUMENTATION_TECH,
        phone="+91-90000-00005",
        telegram_chat_id="demo-instrumentation",
        skills=[FaultType.SENSOR_FAULT],
    ),
    CrewMember(
        name="Kamla Singh",
        role=CrewRole.VWSC_SECRETARY,
        phone="+91-90000-00006",
        telegram_chat_id="demo-vwsc-secretary",
        skills=[FaultType.SOURCE_DEPLETION, FaultType.UNKNOWN],
    ),
    CrewMember(
        name="Block Engineer (PHED)",
        role=CrewRole.BLOCK_ENGINEER,
        phone="+91-90000-00007",
        telegram_chat_id="demo-block-engineer",
        skills=[],
    ),
)

#: What the village store actually holds. A repair needing a part that is not
#: here is slower and needs procurement, which the agent should say out loud
#: rather than discover in the field.
SPARES: tuple[SparePart, ...] = (
    SparePart(part_code="SP-GV-100", name="100mm gate valve", quantity=1, unit_cost=3200.0),
    SparePart(part_code="SP-CLMP-90", name="90mm repair clamp", quantity=4, unit_cost=850.0),
    SparePart(part_code="SP-PIPE-90", name="90mm HDPE pipe (6m)", quantity=2, unit_cost=1900.0),
    SparePart(part_code="SP-STRT-5HP", name="5HP motor starter", quantity=0, unit_cost=6400.0),
    SparePart(part_code="SP-NRV-100", name="100mm non-return valve", quantity=1, unit_cost=2100.0),
    SparePart(part_code="SP-PT-01", name="Pressure transmitter 0-10 bar", quantity=1, unit_cost=4800.0),
    SparePart(part_code="SP-SEAL-KIT", name="Pump seal kit", quantity=2, unit_cost=1200.0),
)

#: Parts a given fault class typically consumes, for the spares check.
PARTS_FOR_FAULT: dict[FaultType, tuple[str, ...]] = {
    FaultType.VALVE_CLOSURE: (),  # opening a valve consumes nothing
    FaultType.PIPELINE_BURST: ("SP-CLMP-90", "SP-PIPE-90"),
    FaultType.PUMP_FAILURE: ("SP-SEAL-KIT", "SP-NRV-100"),
    FaultType.POWER_OUTAGE: ("SP-STRT-5HP",),
    FaultType.SENSOR_FAULT: ("SP-PT-01",),
    FaultType.SOURCE_DEPLETION: (),
    FaultType.THEFT_OR_UNAUTHORISED_TAPPING: ("SP-CLMP-90",),
    FaultType.UNKNOWN: (),
}


def build_vwsc_account(service_area_id: str) -> VwscAccount:
    """The committee's annual maintenance budget and the agent's spend limit.

    These values mirror the `vwsc_accounts` row seeded in Supabase in Phase 1,
    so the offline tests and the deployed demo agree about where the approval
    boundary sits. Changing one without the other would mean the tests prove a
    guardrail that production does not have.

    The limit is where a village committee would realistically set it: high
    enough that routine repairs are not blocked waiting for a meeting, low
    enough that pump work is a human decision.
    """
    return VwscAccount(
        service_area_id=service_area_id,
        fiscal_year=FISCAL_YEAR,
        budget_allocated=250000.0,
        budget_spent=41500.0,
        autonomous_approval_limit=15000.0,
        escalation_contact="Block Development Officer",
    )


def crew_for_role(role: CrewRole) -> CrewMember | None:
    return next(
        (member for member in ROSTER if member.role is role and member.available),
        None,
    )


def spare(part_code: str) -> SparePart | None:
    return next((part for part in SPARES if part.part_code == part_code), None)


__all__ = [
    "FISCAL_YEAR",
    "PARTS_FOR_FAULT",
    "ROSTER",
    "SPARES",
    "build_vwsc_account",
    "crew_for_role",
    "spare",
]
