# May_04_Deniz Final Report Package

Snapshot date: 2026-05-11

Authoritative implementation: `May_04_Deniz/`

This folder is the review-ready final report package for the current `May_04_Deniz` system. It is written as an IEEE-style engineering documentation set: it separates requirements, architecture, detailed design, interface contracts, runtime sequences, security and privacy analysis, validation, operations, and appendices. The documents are intentionally explanatory. A reader should be able to understand the product, reproduce the architecture, and rebuild the implementation from the documented behavior without relying on older snapshots.

The package does not delete or replace the earlier folders `docs/May_04_Deniz_current_spec/` and `docs/May_04_Deniz_rebuild_manual/`. Those remain useful historical and implementation notes. This folder supersedes them as the final report index for the latest implementation.

## Document Index

| File | Purpose |
| --- | --- |
| `01_project_overview.md` | Product context, stakeholders, scope, constraints, system context, and glossary of the core operating model. |
| `02_srs.md` | Software Requirements Specification with functional requirements, non-functional requirements, interfaces, acceptance criteria, and requirement IDs. |
| `03_software_architecture_document.md` | Process topology, module boundaries, deployment model, protocol separation, IPC architecture, and architectural decisions. |
| `04_software_design_document.md` | Detailed design of server, client, GUI, launchers, monitoring, incident rules, replay, submission, auth, projector, reconnect, and IPC. |
| `05_interface_control_document.md` | HTTP, LAN WebSocket, loopback IPC, CLI command, GUI command, persistence, file, and JSON contract inventory. |
| `06_runtime_sequences.md` | End-to-end runtime sequences for startup, discovery, login, exam control, reconnect, monitoring, incidents, replay, submission, projector, settings, and shutdown. |
| `07_security_privacy_and_safety.md` | Security, privacy, safety, local IPC isolation, projection-safe data, authentication bypass controls, evidence handling, and failure containment. |
| `08_testing_and_validation.md` | Automated test inventory, validation strategy, acceptance matrix, regression focus areas, and manual smoke checklist. |
| `09_operations_and_rebuild_manual.md` | Setup, dependencies, run commands, folder layout, data lifecycle, troubleshooting, rebuild order, and deployment notes. |
| `10_appendices.md` | Glossary, acronym table, data-file inventory, risk register, known limitations, future extension points, and historical note. |
| `VALIDATION.md` | Validation record for this documentation package, including commands run and coverage checklist. |
| `llm/system_context_pack.md` | Compact handoff context for an LLM or future engineer. |
| `llm/requirements_traceability.json` | Structured requirements mapped to modules, interfaces, and tests. |
| `llm/module_inventory.json` | Structured module responsibility inventory. |
| `llm/sequence_index.md` | Compact sequence playbook and implementation order. |

## Cross-Reference Map

| Topic | Requirements | Design | Interfaces | Sequence | Validation |
| --- | --- | --- | --- | --- | --- |
| Server HTTP and WebSocket runtime | `FR-SRV-*`, `FR-PROTO-*` | `03`, `04` | `05` | `06` | `08`, `VALIDATION` |
| Client login, discovery, monitoring, and submission | `FR-CLI-*`, `FR-MON-*`, `FR-SUB-*` | `03`, `04` | `05` | `06` | `08`, `VALIDATION` |
| Incident rules and process definitions | `FR-INC-*`, `FR-POL-*` | `04` | `05` | `06` | `08` |
| Reconnect and offline buffering | `FR-REC-*`, `NFR-REL-*` | `03`, `04` | `05` | `06` | `08` |
| Loopback IPC and GUI coordination | `FR-IPC-*`, `NFR-SEC-*` | `03`, `04` | `05` | `06` | `08` |
| Projector read-only notification page | `FR-PROJ-*`, `NFR-PRIV-*` | `03`, `04` | `05` | `06` | `08` |
| Authentication and temporary bypass | `FR-AUTH-*`, `NFR-SEC-*` | `04`, `07` | `05` | `06` | `08` |
| Operations and rebuild | `NFR-OPS-*` | `09` | `05` | `06` | `08`, `VALIDATION` |

## Source Baseline

The report is based on the current source tree under:

- `May_04_Deniz/server`
- `May_04_Deniz/client`
- `May_04_Deniz/common`
- `May_04_Deniz/server/ui`
- `May_04_Deniz/client/ui`
- `May_04_Deniz/launcher_ui`
- `May_04_Deniz/tests`

Older root-level modules and earlier snapshot folders are intentionally out of scope for the authoritative design except as historical context in `10_appendices.md`.

## Reading Order

For a reviewer, read `01`, `02`, `03`, `05`, `07`, and `08`.

For an implementer rebuilding from scratch, read `01`, `03`, `04`, `05`, `06`, and `09`.

For an LLM handoff, start with `llm/system_context_pack.md`, then use `llm/module_inventory.json` and `llm/sequence_index.md`.

## Notation

Requirement IDs use these prefixes:

- `FR-SRV`: server functional requirements
- `FR-CLI`: client functional requirements
- `FR-MON`: monitoring requirements
- `FR-INC`: incident and rule requirements
- `FR-POL`: policy and settings requirements
- `FR-IPC`: local inter-process communication requirements
- `FR-AUTH`: authentication requirements
- `FR-PROJ`: projector requirements
- `FR-SUB`: submission and artifact transfer requirements
- `FR-UI`: GUI and launcher requirements
- `NFR-*`: non-functional requirements

The term "LAN WebSocket" means the student/server runtime protocol exposed by `GET /ws`. The term "loopback IPC" means local-only same-machine process communication implemented by `common.ipc_ws`; it is not the student/server protocol.
