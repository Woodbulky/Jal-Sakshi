"""The words a field actor actually reads.

Composed here, deterministically, from the work order — not by the model and
not by the n8n workflow. Two reasons:

* the message states the SLA, the asset and the work-order code, and those are
  facts about a commitment. A phrasing layer may make them warmer; it may not
  make them different;
* n8n workflows are edited in a browser by someone who is not reading this
  repository. Handing them finished text means a change to how Vitpur is
  addressed is a code change with a test, not a silent edit in a web form.

The LLM's contribution, when there is one, arrives as `action` — a sentence of
instruction that replaces the templated one. Everything around it is fixed.
"""

from __future__ import annotations

from app.schemas.notification import NotificationEvent
from app.schemas.simulation import FaultType
from app.schemas.workorder import WorkOrder

#: Fault classes in the register a village volunteer reads, not SCREAMING_SNAKE.
FAULT_LABELS: dict[FaultType, str] = {
    FaultType.VALVE_CLOSURE: "Valve Closure",
    FaultType.PIPELINE_BURST: "Pipeline Burst",
    FaultType.PUMP_FAILURE: "Pump Failure",
    FaultType.POWER_OUTAGE: "Power Outage",
    FaultType.SOURCE_DEPLETION: "Source Depletion",
    FaultType.SENSOR_FAULT: "Sensor Fault",
    FaultType.THEFT_OR_UNAUTHORISED_TAPPING: "Unauthorised Tapping",
    FaultType.UNKNOWN: "Unclassified Fault",
}


def fault_label(fault_type: FaultType | None) -> str:
    if fault_type is None:
        return "Unclassified Fault"
    return FAULT_LABELS.get(fault_type, fault_type.value.replace("_", " ").title())


def compose(
    event: NotificationEvent,
    order: WorkOrder,
    *,
    fault_type: FaultType | None = None,
    asset_code: str | None = None,
    service_area: str | None = None,
    households_affected: int | None = None,
    assigned_to: str | None = None,
    action: str | None = None,
    reason: str | None = None,
    ttwr_minutes: float | None = None,
) -> str:
    """The Telegram body for one event. Plain text; no markup to escape."""
    match event:
        case NotificationEvent.WORK_ORDER_CREATED:
            return _dispatch(
                order,
                fault_type=fault_type,
                asset_code=asset_code,
                service_area=service_area,
                households_affected=households_affected,
                assigned_to=assigned_to,
                action=action,
            )
        case NotificationEvent.WORK_ORDER_ESCALATED:
            return _escalation(order, reason=reason, assigned_to=assigned_to)
        case NotificationEvent.WORK_ORDER_CLOSED:
            return _closed(order, asset_code=asset_code, ttwr_minutes=ttwr_minutes)
        case NotificationEvent.WORK_ORDER_REOPENED:
            return _reopened(order, asset_code=asset_code, reason=reason)
        case NotificationEvent.APPROVAL_REQUIRED:
            return _approval(order, fault_type=fault_type, reason=reason)
        case NotificationEvent.VERIFICATION_UNVERIFIABLE:
            return _unverifiable(order, asset_code=asset_code, reason=reason)
        case _:
            return f"JAL-SAKSHI {event.value}\n\nWork Order: {order.wo_code}"


def _dispatch(
    order: WorkOrder,
    *,
    fault_type: FaultType | None,
    asset_code: str | None,
    service_area: str | None,
    households_affected: int | None,
    assigned_to: str | None,
    action: str | None,
) -> str:
    lines = [
        "JAL-SAKSHI WORK ORDER",
        "",
        f"Issue: {fault_label(fault_type)}",
    ]
    if service_area:
        lines.append(f"Location: {service_area}")
    if asset_code:
        lines.append(f"Asset: {asset_code}")
    if households_affected:
        lines.append(f"Affected households: {households_affected}")
    lines.append(f"Priority: {order.priority.value}")
    if order.sla_hours:
        lines.append(f"SLA: {_hours(order.sla_hours)}")
    lines += [
        "",
        "Action:",
        action or order.action_summary or "Inspect the asset and report back.",
        "",
        f"Work Order: {order.wo_code}",
    ]
    if assigned_to:
        lines.append(f"Assigned to: {assigned_to}")
    lines.append('Reply "Fixed" when the repair is complete.')
    # Said plainly, because it is the product's central promise and the person
    # replying should know their word starts a check rather than ends one.
    lines.append("Sensors will confirm restoration before this order closes.")
    return "\n".join(lines)


def _escalation(
    order: WorkOrder, *, reason: str | None, assigned_to: str | None
) -> str:
    lines = [
        "JAL-SAKSHI ESCALATION",
        "",
        f"Work Order: {order.wo_code}",
        f"Status: {order.status.value}",
    ]
    if order.sla_hours:
        lines.append(f"SLA: {_hours(order.sla_hours)} — breached")
    if reason:
        lines += ["", reason]
    if assigned_to:
        lines.append(f"Now with: {assigned_to}")
    return "\n".join(lines)


def _closed(
    order: WorkOrder, *, asset_code: str | None, ttwr_minutes: float | None
) -> str:
    lines = [
        "JAL-SAKSHI WORK ORDER CLOSED",
        "",
        f"Work Order: {order.wo_code}",
    ]
    if asset_code:
        lines.append(f"Asset: {asset_code}")
    if ttwr_minutes is not None:
        lines.append(f"Time to water restored: {_minutes(ttwr_minutes)}")
    lines += ["", "Closed on sensor evidence, not on the field report."]
    return "\n".join(lines)


def _reopened(order: WorkOrder, *, asset_code: str | None, reason: str | None) -> str:
    lines = [
        "JAL-SAKSHI WORK ORDER REOPENED",
        "",
        f"Work Order: {order.wo_code}",
    ]
    if asset_code:
        lines.append(f"Asset: {asset_code}")
    lines += [
        "",
        reason or "Telemetry does not confirm restoration. Please return to the site.",
    ]
    return "\n".join(lines)


def _approval(
    order: WorkOrder, *, fault_type: FaultType | None, reason: str | None
) -> str:
    cost = order.estimated_cost or 0.0
    return "\n".join(
        [
            "JAL-SAKSHI APPROVAL NEEDED",
            "",
            f"Work Order: {order.wo_code}",
            f"Issue: {fault_label(fault_type)}",
            f"Estimated cost: ₹{cost:,.0f}",
            "",
            reason or "This exceeds the amount the system may commit on its own.",
            "No crew has been dispatched. A VWSC member must approve the spend.",
        ]
    )


def _unverifiable(
    order: WorkOrder, *, asset_code: str | None, reason: str | None
) -> str:
    lines = [
        "JAL-SAKSHI CANNOT VERIFY",
        "",
        f"Work Order: {order.wo_code}",
    ]
    if asset_code:
        lines.append(f"Asset: {asset_code}")
    lines += [
        "",
        reason
        or "The instruments that would confirm restoration cannot be trusted.",
        "A person must inspect the site. This order will not close by itself.",
    ]
    return "\n".join(lines)


def _hours(value: float) -> str:
    return f"{value:.0f} hours" if value != 1 else "1 hour"


def _minutes(value: float) -> str:
    if value < 90:
        return f"{value:.0f} minutes"
    return f"{value / 60:.1f} hours"


__all__ = ["FAULT_LABELS", "compose", "fault_label"]
