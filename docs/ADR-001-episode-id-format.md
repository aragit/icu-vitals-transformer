# ADR-001: Deterministic Episode ID Format (E-{patient_id})

## Status
Accepted (v0.9.0)

## Context
Episode IDs are generated as `E-{patient_id}` in both `InMemoryEpisodeRepository`
and `RedisEpisodeRepository`. This format was locked in v0.2.0 and is relied upon
by e2e tests and baseline contracts (see `docs/BASELINE.md`).

This was evaluated against an alternative proposal (UUID episode IDs) in the
v0.9.0 gap audit (Task 2.2) but was not migrated because:

1. e2e tests hardcode `E-PT-*` patterns.
2. The baseline lock (BASELINE.md §5.5) records the deterministic format.
3. No multi-episode-per-patient readmission workflow is in scope for v0.9.0.

## Decision
Keep deterministic format `E-{patient_id}` for v0.9.0. Do not migrate to UUIDs
until multi-episode-per-patient readmission tracking is required (R2.1+).

## Consequences
- **Positive**: Backward compatible with all existing tests and client integrations.
  Episode IDs are human-readable and predictable, simplifying debugging and
  log correlation.
- **Negative**: Re-admitting a patient after discharge overwrites/closes the prior
  episode. This is acceptable because the current FSM does not support readmission
  workflows. A second concurrent episode for the same patient would collide on the
  `E-{patient_id}` key.

## Migration Path
When readmission tracking is needed:
1. Change `create()` to `f"E-{patient_id}-{uuid4().hex[:8]}"`.
2. Update e2e tests to use regex matching or capture created IDs dynamically.
3. Add `get_all_active_by_patient()` disambiguation to MCP/REST surfaces (already
  partially scaffolded via MRTR elicitation in `src/adapters/mcp/mrtr.py`).
4. Update `manifests/AGENT_CARD.json` and `manifests/mcp.json` protocol manifests
   to document the new ID format.
