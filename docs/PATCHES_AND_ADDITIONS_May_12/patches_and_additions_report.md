# May 12 Patch And Additions Report

Project: `May_04_Deniz` exam monitoring and management platform

Report type: patch/additions summary and implementation handoff

Date: 2026-05-12

Primary related folders:

- `May_04_Deniz/`
- `May_12/`
- `docs/FINAL_REPORT_May_04_Deniz/`
- `docs/SRS_May_04_Deniz_Overleaf/`

## Abstract

This report summarizes the patches and additions prepared during the May 12
work cycle for the LAN-based laboratory exam system. The work strengthened the
system across server correctness, client reliability, incident-rule handling,
titlebar and executable matching, Tk/Qt dashboard stability, reconnect and
offline buffering, authentication validation, public projector display,
deployment packaging, offline installer security, and documentation. The
changes are grouped by engineering concern so that reviewers can understand not
only what was changed, but also why each change was necessary and how it affects
runtime behaviour.

## 1. Background

The project is a local-area exam platform with one authoritative server and
many student clients. The server owns user state, exam phase, policy, incident
history, submissions, artifacts, and operator commands. The client owns local
monitoring, evidence collection, focused-window observation, process scanning,
timer/submission UI, incident generation, and final upload.

The May 12 patch cycle happened after several earlier snapshots had accumulated
useful but incomplete fixes. The goal was to stabilize the latest
`May_04_Deniz` implementation and prepare a deployment-ready split under
`May_12`.

## 2. Report Structure

This report follows the same broad structure as the previous engineering
reports:

1. Baseline and scope.
2. Patch inventory.
3. Design and implementation details.
4. Security, privacy, and deployment impact.
5. Validation summary.
6. Known limitations and next steps.

## 3. Baseline And Scope

The authoritative source baseline is `May_04_Deniz/`. Older folders and
previous snapshots are treated as historical reference only.

The deployment output baseline is `May_12/`, which separates the project into:

- `May_12/setup`
- `May_12/client`
- `May_12/server`

The report covers patches and documentation prepared in the current chat-driven
work sequence. It does not claim that every older snapshot was fully merged.

## 4. Patch Inventory

| Area | Problem | Patch or Addition | Main Effect |
| --- | --- | --- | --- |
| May 10 server patches | May 10 fixes existed in a newer snapshot but could not be copied wholesale without regressing newer work. | Manually isolated safe-close-message, secured error response, and banned-user finish fixes. | Preserved current code while importing server-side regressions fixes. |
| Global finish | `/finishexam` could reset banned users into awaiting submission. | Banned users are skipped during global finish and skipped count is reported. | Banned state remains authoritative. |
| WebSocket close reason | Long close messages could exceed control-frame byte limits and be swallowed silently. | Safe UTF-8 trimming helper added for close reasons. | Disconnect reasons remain deliverable without splitting UTF-8. |
| Secured malformed event error | Encrypted sessions could receive malformed process-catch errors as plain text. | Error response is wrapped through the existing protection path. | Security envelope consistency is preserved. |
| Incident rules | Focused-window policy was mostly global string lists. | Added definition-style incident rules with whitelist, warning, blacklist, priority, match mode, and actions. | Operator decisions become reusable policy. |
| Titlebar save logic | Saved rules captured full browser titles and over-restricted process names. | Save-as-rule defaults to reusable `contains` title patterns and title-only scope. | Rules like `whatsapp` match future browser variants. |
| Unicode titlebar safety | Edge/Yandex/browser titles with invisible Unicode characters could break matching. | Title normalization and sanitization are applied before matching and persistence. | Monitoring does not silently fail on titlebar edge cases. |
| Browser approvals | Approved browser pages needed to be configurable without URL extraction. | Whitelist titlebar rules support New Tab and configurable approved sites. | Browser approvals remain title-based and policy-driven. |
| Executable matching | Blocking one desktop app required too many exact process names. | Wildcard-compatible process matching was added. | One rule can cover app executable families. |
| Tk/Qt list refresh | Live updates rebuilt tables and reset scrollbars every second. | Stable row fingerprints, in-place value updates, and scroll/selection preservation were added. | Operators can review long lists while updates arrive. |
| Tk/Qt row hover | Hover highlighted only one cell in some lists. | Full-row hover behaviour added for table/tree widgets. | Rows are easier to scan visually. |
| Reconnect logging | WebSocket disconnect could stop local monitoring/logging. | Persistent runtime design keeps monitors, GUI, replay, incidents, and logs alive across reconnect. | Local evidence continues during network failures. |
| Offline incident buffer | Incidents generated while disconnected could be dropped or restored twice. | Buffered incidents use sequence metadata, queued timestamps, disk persistence, ordered flush, and dedupe. | Incident delivery is resilient to disconnects. |
| Exam files | Exam material extraction needed safer desktop handling. | ZIP extraction rejects unsafe paths and uses managed dated Desktop Exam folders. | Student materials are accessible without unsafe overwrite behaviour. |
| Folder info UI | Operators and students needed visibility into local/server folder paths. | Client Exam Folder button and server selected-user folder info were added. | File-location support improves operations. |
| Auth disable | Temporarily disabling CATS/AD could be misunderstood as direct bypass. | Disabled auth creates admin validation state with approve/deny commands. | Auth recovery remains operator-controlled. |
| Projector frontend | Dashboard UI was not suitable for large low-resolution projection. | Added `/projector` page and `/projector/events` SSE feed. | Classroom display shows public-safe notifications. |
| Projector assets | Inline frontend code is hard to maintain. | HTML, CSS, and JavaScript were split into static files. | Frontend is reviewable and maintainable. |
| Documentation | Existing docs needed review-ready SRS/final report structure. | Added final report package, SRS package, Overleaf-compatible files, and contribution reports. | Project is easier to review and rebuild. |
| Offline installer | Machine-wide pip installs are risky. | Setup uses shared/per-bundle virtual environments, local wheelhouse, manifest verification, and clearer permissions. | Dependency conflicts are reduced. |
| Python compatibility | Python 3.14 requires compatible wheels. | Documented that current wheelhouse is Python 3.13 oriented and must be rebuilt for Python 3.14. | Prevents mixed ABI deployment failures. |
| Deployment split | Client and server files were mixed in source tree. | Created `May_12/setup`, `May_12/client`, and `May_12/server`. | Student and operator deployment bundles are independent. |
| Repository hygiene | Runtime data, logs, and binary payloads risked entering Git. | Expanded `.gitignore`. | Sensitive/generated files are ignored by default. |
| Overleaf docs | Existing group paper had a placeholder for Ahmet's contribution. | Added named and no-name contribution snippets plus standalone IEEE reports. | Contribution material is ready for Overleaf insertion. |

## 5. Server-Side Patches

### 5.1 Safe Finish Behaviour

The global finish command had a state regression risk: finishing all users could
move banned users into an awaiting-submission state. This is incorrect because
ban state is an operator/security decision and must not be forgiven by a global
phase transition.

The patched behaviour skips users where the user record is banned or where the
derived session state is banned. The exam phase can still move forward, but the
command output reports the number of skipped banned users.

### 5.2 Safe WebSocket Close Messages

WebSocket close frames have a small payload limit. Long policy reasons,
especially with multi-byte characters, can exceed this limit. A naive trim can
also split a UTF-8 sequence and create invalid close data.

The patch adds safe byte-length trimming while respecting UTF-8 character
boundaries. This allows close reasons to remain useful while preventing silent
send failures.

### 5.3 Security Envelope Consistency

When a client is using a secured session context, error responses for malformed
events must be protected just like normal sensitive events. The malformed
process-catch path was corrected so encrypted/signable sessions receive a
protected error response.

## 6. Incident Rules And Matching

### 6.1 Incident Rules

Incident rules make operator decisions persistent and reusable. Instead of a
single global title list, a rule can define:

- status: `unknown`, `whitelist`, `warning`, `blacklist`
- event type
- source
- process names
- browser process names
- window title patterns
- match mode
- priority
- configured actions

Whitelist rules suppress incidents before warning/blacklist rules. Warning and
blacklist rules can override severity and attach action metadata.

### 6.2 Titlebar Matching

The titlebar matcher was redesigned around reusable patterns. Saving the whole
observed title is fragile because browser titles change often. The improved
behaviour prefers compact `contains` patterns such as `whatsapp`, strips common
browser suffixes, and leaves process restrictions empty by default for
titlebar-style rules.

This approach supports browser-title variants without URL extraction. Approved
websites such as exam tools can be configured as whitelist title patterns, while
New Tab can be shipped as a default whitelist rule.

### 6.3 Unicode And Invisible Character Safety

Titlebar text can include invisible whitespace/control characters. The matcher
now treats sanitization and normalization as part of the policy boundary. This
prevents titlebar edge cases from silently disabling incident detection.

### 6.4 Executable Wildcards

Executable matching was extended so one process rule can match an application
family. This is important for desktop apps with helper executables or variant
binary names. Existing exact and contains definitions remain compatible.

## 7. UI Stabilization

### 7.1 Smooth Refresh

The dashboard previously rebuilt lists on frequent updates, especially timer
ticks. This reset vertical scroll, horizontal scroll, focus, and selection.

The new approach tracks row identity, order, and content fingerprints. If row
identity/order is stable, values are updated in place. If a rebuild is required,
scroll and selection are restored. Timer countdown updates avoid unnecessary
re-sorting.

### 7.2 Full-Row Hover

Tk and Qt table/list views now visually highlight the full hovered row instead
of only one cell. Selected-row styling remains stronger than hover styling.

## 8. Reconnect, Buffering, And Evidence

The reconnect sequence was redesigned so network disconnects do not stop local
logging. Long-lived local runtime components remain active:

- process monitor
- focused-window monitor
- idle monitor
- hardware monitor
- exam-state logger
- timer/submission GUI bridge
- incident engine
- incident buffer
- replay recorder

Incidents generated while disconnected are queued with stable metadata and
flushed after reconnect. Evidence upload status is persistently retried.

## 9. Exam Files And Folder Info

Exam material download now keeps a ZIP copy under client data and safely
extracts materials to a dated Desktop Exam folder. The extractor rejects unsafe
archive members and protects unmarked user folders from deletion.

The client UI can show an Exam Folder button after extraction. The server
dashboard can show selected-user folder information, including expected client
folder and server-side submission/artifact paths.

## 10. Authentication Validation

Temporary CATS/AD disable is treated as controlled recovery, not unrestricted
access. The client asks the server for auth status. If auth is temporarily
disabled, matching login attempts enter admin validation. Operators can inspect,
approve, or deny attempts.

Relevant commands include:

- `/disablecatsauth`
- `/disableadauth`
- `/disableauth`
- `/enablecatsauth`
- `/enableadauth`
- `/enableauth`
- `/authstatus`
- `/authrequests`
- `/approveauth`
- `/denyauth`

The validation workflow is runtime-only and does not persist submitted
passwords.

## 11. Projector Frontend

The read-only projector page is intended for classroom display on low-resolution
large screens. It uses large text, high contrast, and generic notifications.
The frontend is served as separate HTML, CSS, and JavaScript assets, while the
SSE endpoint streams public-safe aggregate state.

The projector payload excludes:

- login IDs
- UUIDs
- IP addresses
- process names
- window titles
- artifact paths
- submission paths
- evidence details

## 12. Documentation Additions

The documentation work added:

- final IEEE/SRS-grade report package
- SRS Markdown and Overleaf-compatible LaTeX files
- contribution snippets for the existing group Overleaf document
- named and no-name contribution variants
- standalone IEEE contribution reports
- deployment split validation notes
- patch/additions report package

These files support review, future maintenance, and project reconstruction.

## 13. Offline Installer And Setup Hardening

The installer/setup direction was changed to avoid risky machine-wide pip
package installation. Packages are installed into a virtual environment rather
than global Python `site-packages`.

The setup assets include:

- local wheelhouse
- optional Python installer
- FFmpeg binaries
- SHA-256 manifest
- batch/PowerShell setup scripts

The current copied wheelhouse is Python 3.13 / Windows x64 oriented. It must be
rebuilt before targeting Python 3.14 or another ABI/platform.

## 14. May_12 Deployment Split

The `May_12` folder was created with three deployable units:

| Folder | Purpose |
| --- | --- |
| `setup/` | Shared offline dependency assets and setup scripts. |
| `client/` | Standalone client deployment bundle. |
| `server/` | Standalone server/operator deployment bundle. |

Shared code such as `common/` and UI helpers is duplicated so client and server
can deploy independently. The client bundle does not contain the server package,
and the server bundle does not contain the client package.

## 15. Repository Hygiene

The `.gitignore` file was expanded to ignore:

- Python caches
- virtual environments
- runtime logs
- JSONL traces
- runtime client/server data
- artifacts and submissions
- generated recordings
- archives
- heavy installer binaries
- offline wheelhouse payloads

Safe policy defaults are explicitly kept versionable.

## 16. Validation Summary

Validation performed during the work sequence included:

| Check | Result |
| --- | --- |
| `python -m compileall -q .` on `May_04_Deniz` | Passed |
| `python -m unittest discover -s tests` on `May_04_Deniz` | 168 tests passed |
| `python -m pip check` | No broken requirements found |
| Offline pip dry-run from local wheelhouse | Passed |
| Manifest verification | Passed |
| `May_12/client` compile check | Passed |
| `May_12/server` compile check | Passed |
| `May_12` client/server cross-import scan | Passed |
| CLI help import checks for split bundles | Passed |
| Overleaf snippet ASCII checks | Passed |

The Git CLI was not available in the shell during `.gitignore` validation, so
`git check-ignore` could not be run directly.

## 17. Known Limitations

- The current wheelhouse is still Python 3.13 oriented; Python 3.14 requires a
  rebuilt wheelhouse.
- Some UI behaviours still require manual smoke testing on actual Windows 11 lab
  machines.
- The titlebar browser approval model is intentionally title-based only; it does
  not extract URLs.
- Offline installer scripts were validated syntactically and through dry-runs,
  but a full elevated install was not executed in this workspace.
- `pdflatex` was not available locally, so Overleaf/LaTeX documents were not
  compiled locally.

## 18. Conclusion

The May 12 patch cycle significantly improved the exam platform's reliability,
policy maintainability, operator usability, privacy posture, deployment
readiness, and documentation quality. The most important architectural result is
that transient network loss no longer implies local evidence loss. The most
important policy result is that titlebar and process decisions are now reusable
definitions rather than one-off strings. The most important operational result
is the `May_12` deployment split, which separates client, server, and setup
responsibilities for cleaner deployment.

