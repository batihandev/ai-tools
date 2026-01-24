---
trigger: always_on
---

# Engineering Standard: Logic Consolidation & Maintainability

## Objective

Reduce redundancy and improve maintainability by ensuring every piece of logic has a single, unambiguous source of truth while preserving existing project structures.

## Hard Rules (Must Not Violate)

- **Zero-Copy Policy:** Do not copy-paste logic across files, layers, or components. Shared logic must be extracted.
- **No Duplicate Logic:** Do not introduce logic that duplicates existing functionality, even if the implementation differs slightly.
- **No Redundant Abstractions:** Do not create new components, utilities, or hooks if an equivalent already exists.
- **Preserve Structure:** Do not restructure the project unless redundancy cannot be resolved otherwise.
- **Stable Naming:** Maintain existing names for variables, functions, and types unless a change is strictly required for correctness.

## Required Behavior

### 1. Discovery & Reuse

- **Search First:** Always search for existing components, composables, hooks, or utilities before writing new code.
- **Prefer Reuse:** Prioritize adapting an existing utility over creating a new "alternative" version.

### 2. Strategic Extraction (The Rule of Three)

- **First Instance:** Implement locally and simply.
- **Second Instance:** Local implementation is acceptable, but note the duplication.
- **Third Instance:** Mandatory extraction. Extract shared logic into a single reusable unit and replace all three original usages with that unit.

### 3. State & Logic Discipline

- **Minimal State:** Remove unused or derivable state. If a value can be computed from existing props/state, do not store it.
- **Thin Components:** Components should be "view-only" and delegate business logic to shared layers (hooks, services, or utilities).
- **Explicit Boundaries:** Maintain clear ownership boundaries. Avoid leaking state across unrelated contexts.
- **Focused Units:** Prefer small, single-purpose utilities over large multipurpose ones.

## Code Quality Standards

- **Single Source of Truth:** Business logic must exist in exactly one place.
- **Incremental Changes:** Changes must be local and incremental rather than sweeping architectural shifts.
- **Naming Consistency:** Naming must remain consistent with the existing codebase patterns.

## Evaluation Checklist (Self-Review)

- [ ] **Discovery:** Did I check if an equivalent component or utility already exists?
- [ ] **Redundancy:** Is any logic duplicated after my change?
- [ ] **Abstraction:** If I extracted logic, did I update all previous instances to use the new unit?
- [ ] **State:** Is all state necessary, or can some of it be derived?
- [ ] **Stability:** Did I keep existing names unless change was absolutely necessary for clarity?
- [ ] **Structure:** Does this improve the current structure rather than replace it?
