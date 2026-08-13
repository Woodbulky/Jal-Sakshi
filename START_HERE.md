# JAL-SAKSHI Dual-Agent Build Handoff

This package defines the collaboration model for two coding agents.

## Roles

### Claude Code
Primary system engineer. Owns backend, database, agent orchestration, simulation, business logic, integrations, testing, and deployment-critical code.

### Antigravity
Frontend/product engineer. Owns landing page, operations console, map visualization, charts, animations, responsive UI, and demo controls.

## Read first

Both agents must read the files in `shared/` before coding.

## Build order

1. Claude Code builds the backend/data/agent skeleton.
2. Claude Code builds telemetry simulation and fault detection.
3. Claude Code builds work orders, SLA, escalation, and verification.
4. Claude Code defines n8n + Telegram contracts.
5. Antigravity builds the frontend against those contracts.
6. Claude Code integrates the frontend and backend.
7. Antigravity performs visual polish.
8. Claude Code runs full tests and prepares deployment.

## Core product idea

JAL-SAKSHI is an agentic AI rural-water operations layer that turns water-network anomalies into accountable action, communicates work through n8n/Telegram, and closes incidents only after sensor evidence verifies restoration.

Vitpur is only a fictional demo service area. It is not the project itself.
