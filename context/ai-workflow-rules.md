# AI Workflow Rules

## Approach

Build this homelab infrastructure incrementally using a spec-driven workflow.
Context files define what to build, how to build it, and
the current state of progress. Always implement against
these specs — do not infer or invent behavior from scratch.

## Scoping Rules

- Work on one feature unit at a time (e.g., a specific service, network configuration, or automation tool)
- Prefer small, verifiable increments over large speculative changes
- Do not combine unrelated system boundaries in a single implementation step
- Each PR should address a single concern or feature

## When to Split Work

Split an implementation step if it combines:

- Multiple unrelated services or configurations
- Behavior not clearly defined in the context files
- Changes that affect both infrastructure and application layers

If a change cannot be verified end to end quickly (via tests or examples),
the scope is too broad — split it.

## Handling Missing Requirements

- Do not invent behavior not defined in the context files
- If a requirement is ambiguous, resolve it in the relevant context file before implementing
- If a requirement is missing, add it as an open question in `progress-tracker.md` before continuing
- When unsure about best practices or conventions, consult existing configurations in the repository

## Protected Files

Do not modify the following unless explicitly instructed:

- Docker-compose files and container configurations (unless updating the service)
- Generated files (those should be regenerated, not edited)
- CI configuration files unless updating the CI process
- Secret management files (unless rotating credentials)

## Keeping Docs in Sync

Update the relevant context file whenever implementation changes:

- System architecture or boundaries (update architecture-context.md)
- Storage model decisions (update architecture-context.md)
- Code conventions or standards (update code-standards.md)
- Feature scope (update project-overview.md)
- Add new services to project-overview.md when they become stable
- Document new configurations in architecture-context.md or code-standards.md as appropriate

## Before Moving to the Next Unit

1. The current unit works end to end within its defined scope (test with examples or test suite)
2. No invariant defined in `architecture-context.md` was violated
3. `progress-tracker.md` reflects the completed work
4. All tests pass (or equivalent validation command)
5. Configuration validation passes (if applicable)
6. Examples in the examples/ directory still work (if relevant)
