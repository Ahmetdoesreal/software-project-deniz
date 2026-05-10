# May_04_Deniz Current Spec

Snapshot date: 2026-05-10

This folder documents the current `May_04_Deniz` implementation and the local IPC migration.

## Layout

- `human/`: readable feature and sequence documentation for engineers and reviewers.
- `llm/`: compact context packs intended for LLM handoff, code review, and future implementation work.

The local WebSocket IPC documented here is same-machine process IPC only. It does not replace the LAN-facing exam server/client WebSocket protocol.
