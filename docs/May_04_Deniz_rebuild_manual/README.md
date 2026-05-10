# May_04_Deniz Professional Rebuild Manual

Snapshot date: 2026-05-10

Source implementation: `May_04_Deniz/`

This documentation set is intentionally broader and more explanatory than the current-spec folder. Its goal is to let a developer or an LLM recreate the project from scratch by following the responsibilities, data contracts, algorithms, runtime sequences, and module boundaries described here.

The application is a LAN exam runtime with:

- A server process that owns exam state, student sessions, policy, submissions, artifacts, and operator commands.
- A client process that authenticates a student, discovers or connects to the server, runs monitoring modules, reports incidents, shows a timer/submission UI, and uploads final work.
- Tk and Qt GUI variants for the server dashboard, student timer/submission window, and manager launchers.
- A loopback-only authenticated WebSocket IPC layer for parent/child process control, with stdio fallback for manual console use.
- A checksum-protected LAN WebSocket event protocol, with optional secured payloads for sensitive events.

## Folder Layout

- `human/01_system_architecture.md`: project purpose, process topology, module boundaries, dependency model, and rebuild principles.
- `human/02_server_rebuild_manual.md`: server implementation guide covering app creation, routes, state, WebSocket handling, commands, settings, persistence, and shutdown.
- `human/03_client_rebuild_manual.md`: client implementation guide covering discovery, login, exam preparation, WebSocket runtime, GUI coordination, monitoring, incidents, replay, and submission.
- `human/04_policy_incident_monitoring.md`: detailed policy schema, normalization rules, incident algorithms, process definition logic, auto actions, and evidence capture.
- `human/05_local_ipc_gui_transport.md`: local WebSocket IPC, stdio fallback, process launch patterns, GUI command/state channels, and Windows windowed-process rules.
- `human/06_runtime_sequences.md`: long-form startup, login, policy sync, timer, monitoring, replay, submission, settings, IPC, and shutdown sequences.
- `human/07_data_contracts_and_operations.md`: HTTP contracts, WebSocket events, IPC envelopes, storage files, setup, tests, validation, and rebuild checklist.
- `llm/rebuild_context_pack.md`: compact high-signal context for LLM handoff.
- `llm/module_contracts.json`: structured module responsibility map.
- `llm/sequence_playbook.md`: condensed sequence and algorithm index for implementation work.

## Rebuild Order

If rebuilding the project from scratch, implement it in this order:

1. Shared contracts: `common.protocol`, `common.events`, `common.security`, discovery, process definitions, runtime logging, and local IPC.
2. Server state and persistence: users, policy, blacklist, process definitions, incidents, audit, submissions, artifacts.
3. Server HTTP and WebSocket routes.
4. Server background tasks and operator command handlers.
5. Client authentication, discovery, exam preparation, and WebSocket loop.
6. Client monitors and incident engine.
7. Transfers, replay recorder, and final submission.
8. GUI windows and manager launchers.
9. Local IPC integration between launchers, CLIs, and GUI child windows.
10. Tests and operational validation.

## Scope

This manual describes the May_04_Deniz implementation after the loopback IPC migration and idle-policy UI patch. It treats the LAN server/client WebSocket protocol and the local process IPC protocol as separate systems. Local IPC is same-machine only and must not be exposed to students or the LAN.

