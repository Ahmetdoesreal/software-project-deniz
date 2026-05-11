# 10. Appendices

## Appendix A. Glossary

| Term | Meaning |
| --- | --- |
| Artifact | Runtime evidence uploaded separately from final submission, such as replay or incident bundle. |
| CATS | School authentication/preflight integration used before client login where configured. |
| Dashboard | Server-side operator UI that displays clients, incidents, policy, process database, and commands. |
| Exam files | Server-provided ZIP materials downloaded and extracted on student machines. |
| Incident | A policy-relevant event such as blacklisted process, forbidden focused window, idle threshold, or saved rule match. |
| Incident rule | Definition-based rule that can whitelist, warn, or blacklist future incident candidates. |
| LAN WebSocket | Student/server runtime WebSocket exposed by `/ws?id=<uuid>`. |
| Local IPC | Same-machine IPC between app-owned local processes; implemented with loopback WebSocket or stdio fallback. |
| Process definition | Server-managed process database entry used to classify known, warning, blacklisted, or allowed processes. |
| Projector | Read-only public display page served by `/projector`. |
| Replay | Recent screen recording saved by the client recorder after a server request or incident flow. |
| Session UUID | Server-assigned client session identifier used for routes, WebSocket, data folders, and uploads. |

## Appendix B. Acronyms

| Acronym | Expansion |
| --- | --- |
| AD | Active Directory |
| API | Application Programming Interface |
| CLI | Command-Line Interface |
| GUI | Graphical User Interface |
| HMAC | Hash-Based Message Authentication Code |
| HTTP | Hypertext Transfer Protocol |
| IPC | Inter-Process Communication |
| JSON | JavaScript Object Notation |
| LAN | Local Area Network |
| SSE | Server-Sent Events |
| SRS | Software Requirements Specification |
| UI | User Interface |
| UUID | Universally Unique Identifier |
| WS | WebSocket |

## Appendix C. Data File Inventory

| File or folder | Purpose |
| --- | --- |
| `allowed_users.json` | Allowed login id source. |
| `auth_config.json` | Client/server auth-related local configuration. |
| `data/server/users.json` | Persistent users and session metadata. |
| `data/server/exam_policy.json` | Exam policy settings. |
| `data/server/process_blacklist.txt` | Legacy process blacklist. |
| `data/server/process_definitions.json` | Process database definitions. |
| `data/server/incident_rules.json` | Incident rule definitions. |
| `data/server/incidents.json` | Incident history. |
| `data/server/submissions/` | Final uploaded student submissions. |
| `data/server/artifacts/` | Uploaded runtime artifacts and evidence. |
| `data/logs/server/` | Server runtime logs. |
| `data/logs/client/` | Client runtime logs. |
| `data/client/{uuid}/buffer/` | Durable incident/evidence retry queue. |
| `data/client/{uuid}/recordings/` | Replay cache and saved replays. |
| `data/client/{uuid}/exam_files/` | Downloaded exam materials copy. |
| `Desktop/Exam/DD-MM-YYYY` | Extracted student-facing exam materials. |

## Appendix D. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Network disconnect during exam | Lost server connection and possible incident send failure. | Persistent reconnect loop, local logging continuation, incident buffer, evidence retry. |
| Duplicate server id | Clients may connect to wrong server. | Startup duplicate precheck and runtime duplicate guard. |
| Browser titlebar edge case | Focused-window matching may miss or break on unusual characters. | Text safety normalization and incident-rule title matching. |
| Unsafe exam ZIP | Path traversal or accidental overwrite. | Safe extraction, managed manifest, unmarked-folder protection. |
| Public display leaks data | Privacy breach on projection screen. | Projection-safe payload builder and tests. |
| GUI refresh disruption | Operator loses scroll/selection during live updates. | Row fingerprint helpers and in-place updates. |
| Missing Qt dependency | Qt UI cannot run. | Tk UI remains available; PySide6 is optional. |
| FFmpeg recorder failure | Replay not available or incomplete. | TS fallback and error logging. |
| Manual policy edit error | Invalid JSON or broken config. | Normalization defaults, apply commands, settings tests. |

## Appendix E. Known Limitations

- The server is intended for LAN operation, not public internet exposure.
- Browser approval is based on titlebar matching and process name, not browser URL extraction.
- Killing a browser titlebar incident kills the browser process id, not a single tab.
- Client-side monitoring cannot prevent all tampering by a determined local administrator.
- Replay quality and availability depend on FFmpeg and desktop capture compatibility.
- Qt mode depends on PySide6 installation and platform stability.
- The projector page is public-safe, not an administrative dashboard.

## Appendix F. Future Extension Points

- Stronger authentication integration with centralized identity providers.
- Signed settings bundles and stricter policy provenance tracking.
- More precise browser integration through controlled extensions or accessibility APIs.
- Dedicated operator audit log export format.
- Richer projector themes or room layouts while preserving privacy rules.
- Per-course or per-exam profile management.
- Automated packaging for Windows deployment.
- Optional encrypted-at-rest storage for submissions and artifacts.

## Appendix G. Historical Note

The repository contains older snapshots and root-level modules predating `May_04_Deniz`. They show project evolution and may contain useful comparison material, but this final report treats `May_04_Deniz/` as the normative implementation. Earlier docs in `docs/May_04_Deniz_current_spec/` and `docs/May_04_Deniz_rebuild_manual/` remain preserved for continuity.
