# Safety Protocol for Script Execution

## Safety Levels

Every function in the callable catalog has a `safety_level` field. This determines
how the AI should handle execution requests.

### `read_only`

**Functions that only read state — no side effects.**

- **Pattern**: Names starting with `Get`, `Find`, `Is`, `Has`, `Does`, `Can`, `Contains`,
  `Was`, `Are`, `Num`, `Count`, `Check`, `Query`, `Lookup`, `Search`, `List`
- **Action**: Execute immediately without user confirmation
- **Examples**:
  - `GetAllActorsOfClass()` — lists actors
  - `IsValid()` — checks validity
  - `FindObject()` — locates an object
  - `GetActorLocation()` — reads transform

### `editor_modify`

**Functions that modify editor state but are non-destructive (reversible via undo).**

- **Pattern**: Any function not matching read_only or destructive patterns
- **Action**: Inform the user what the operation will do, then execute
- **Examples**:
  - `SetActorTransform()` — moves an actor
  - `SpawnActor()` — creates a new actor
  - `SetMaterial()` — changes material assignment
  - `CompileBlueprint()` — recompiles a blueprint

### `destructive`

**Functions that permanently remove data or have hard-to-reverse effects.**

- **Pattern**: Names starting with `Delete`, `Destroy`, `Remove`, `Clear`,
  `Reset`, `Purge`, `Unregister`
- **Action**: **Require explicit user confirmation** before executing
- **Examples**:
  - `DeleteAsset()` — permanently deletes an asset
  - `DestroyActor()` — removes an actor from the level
  - `RemoveComponent()` — removes a component from an actor
  - `ClearLevel()` — clears all actors in a level

## Escalation Rules

1. **When in doubt, escalate UP.**
   If the safety level is ambiguous, treat it as the higher risk level.

2. **Batch operations always escalate.**
   Executing the same operation on multiple objects should always require confirmation,
   even for `editor_modify` operations. E.g., "set material on all 500 actors" → confirm.

3. **Chained destructive operations require per-chain confirmation.**
   If a script combines multiple destructive operations, confirm the entire script, not
   each individual call.

4. **Undo context.**
   When executing `editor_modify` operations, remind the user that Ctrl+Z (undo)
   is available in the editor.

## Confirmation Format

When requesting confirmation for destructive operations:

```
⚠️ This operation will DELETE [specific items].
This action cannot be undone via the editor's undo system.

Proceed? (Provide the specific operation details so the user can make an informed decision)
```

## Error Handling

- If Python execution returns `success: false`, display the error and log output
- If the MCP connection fails, inform the user that the editor must be running
- Never retry destructive operations automatically on failure
- For `editor_modify` failures, suggest checking the editor log for details
