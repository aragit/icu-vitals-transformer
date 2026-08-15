# ADR-001: Episode ID Format

## Status
- Accepted v0.9.0 — deterministic format `E-{patient_id}`.
- **Superseded v0.9.1** — migrated to UUID-based format `E-<uuid>` to support
  multiple concurrent episodes per patient (readmission tracking) and to
  eliminate ID collisions on the active-patient index.

## Context
Episode IDs were generated as `E-{patient_id}` in both
`InMemoryEpisodeRepository` and `RedisEpisodeRepository`. This deterministic
format (locked in v0.2.0) assumed a single active episode per patient and
collided whenever a second episode was created for the same patient — the
second `create()` overwrote the active index, so resolving multiple active
episodes was effectively dead code for the default backend.

## Decision (v0.9.1)
Generate episode IDs as `E-{uuid.uuid4().hex[:12]}` at `create()` time in
both repositories:
- `src/adapters/storage/memory.py` → `InMemoryEpisodeRepository.create`
- `src/adapters/storage/redis.py` → `RedisEpisodeRepository.create`

This makes the format `E-<12-hex-char-uuid>`. Both repositories now key their
active-patient index on a **set** of episode IDs (`dict[str, set[str]]` in
memory, `SADD`/`SMEMBERS` in Redis), so multiple concurrent episodes per
patient are tracked and multi-episode disambiguation
(`discover_episode` / `get_all_active_by_patient`) is reachable.

`get_active_by_patient()` returns the most recent active episode deterministically
(ordering by `Episode.created_at`) for both backends; `E-{patient_id}` exact
value assertions in tests were replaced with `startswith("E-")` + UUID-suffix
length checks, and tests that need the id now capture it from the ingest
response.

## Consequences
- **Positive**: Multiple active episodes per patient are now supported; the
  active-patient index no longer collides; multi-episode disambiguation is
  reachable in the default backend; ID generation is collision-free.
- **Negative**: Episode IDs are no longer human-guessable from the patient id;
  log correlation must use `patient_id` + `episode_id` rather than inferring one
  from the other.
- **Migration**: No on-disk format migration is required — in-memory state is
  ephemeral and Redis episodes are re-created per new admission. Clients must
  capture `episode_id` from the ingest/open response rather than constructing it.

## Migration Path (completed)
1. `create()` → `f"E-{uuid.uuid4().hex[:12]}"` in both repositories.
2. Tests capture created IDs dynamically from the ingest/open response.
3. `get_active_by_patient()` made deterministic (latest-by-`created_at`) for
   both backends; `get_all_active_by_patient()` returns the full active set.
4. `docs/ARCHITECTURE.md` §4.6 and this ADR updated to the v0.9.1 contract.
