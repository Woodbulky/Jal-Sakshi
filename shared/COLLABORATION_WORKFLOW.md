# Claude Code + Antigravity Collaboration Workflow

## Golden rule

Claude Code owns architecture and system-of-record logic.

Antigravity owns isolated frontend/product work.

## Claude Code may modify

```text
backend/
supabase/
simulation/
n8n/ contracts/configuration
docs/architecture
```

## Antigravity may modify

```text
frontend/app
frontend/components
frontend/hooks
frontend/lib/ui helpers
frontend/types
```

## Do not do

Do not have both agents independently redesign the database or API contract.

## API change procedure

1. Update `shared/API_CONTRACT.md`.
2. Update backend.
3. Update frontend integration.
4. Run integration tests.

## Recommended git branches

```text
main
claude/core
antigravity/frontend
```

Claude Code should perform the final merge when both agents touched the same file.
