# Suggested Changes for `Overleaf_existing.txt`

These are suggested edits only. They are not applied to the original group
Overleaf document.

## 1. Fix Character Encoding

The current `Overleaf_existing.txt` appears to contain mojibake in Turkish names
and text, for example `Åevval`, `BarÄ±ÅŸ`, and `Ä°stanbul`. Before final
submission, restore the document as UTF-8 so names and Turkish characters render
correctly in Overleaf.

Suggested corrected examples:

- `Şevval Naz Özkaraca`
- `Barış Bağbekleyen`
- `Ahmet Deniz Sezgin`
- `İstanbul Kültür University`
- `Türkiye`

## 2. Update Test Counts

The abstract and testing sections currently mention `149 of 151` passing tests.
The current local validation after later patches is:

- `python -m unittest discover -s tests`: 168 tests passed
- `python -m compileall -q .`: passed
- `python -m pip check`: no broken requirements found

Update the paper if the final source snapshot is the latest `May_04_Deniz`
implementation rather than the older milestone.

## 3. Add Ahmet Deniz Section

Replace the placeholder:

```latex
\subsection{Ahmet Deniz --- Client-Side Developer}
% TODO...
```

with the contents of:

```text
Overleaf_Ahmet_Deniz_additions.tex
```

The optional table at the end of that snippet can be removed if the IEEE page
limit is tight.

## 4. Keep Contribution Sections Balanced

Some contribution subsections are very detailed, while others are still TODO.
For a final group report, make each member section roughly similar in length and
specificity. A good target is:

- 2 to 4 paragraphs per person
- specific modules/files where possible
- specific bugs/features/tests where possible
- no generic claims without implementation evidence

## 5. Update Abstract After All Contributions Are Final

The abstract currently claims approximately `30,000 lines of Python` and a
specific test count. Re-check these values after the final folder split and
documentation additions. If exact line count is not required, use a safer phrase
such as:

```latex
The implementation consists of multiple Python packages covering server,
client, shared protocol logic, monitoring modules, graphical interfaces, and
deployment tooling.
```

## 6. Add Deployment Split To Results Or Future Work

The current paper describes architecture but does not mention the final
`May_12` deployment split. Consider adding one sentence to Results or Future
Work:

```latex
For deployment, the final snapshot was separated into independent
\texttt{client}, \texttt{server}, and \texttt{setup} bundles so that student and
operator machines can be provisioned without mixing runtime responsibilities.
```

## 7. Clarify Projector Asset Separation

The projector section should mention that the HTTP frontend is now separated
into HTML, CSS, and JavaScript files, not embedded as one large string. This is
useful because it improves maintainability and reviewability.

Suggested sentence:

```latex
The projector frontend is served as separate HTML, CSS, and JavaScript assets,
while the SSE endpoint remains read-only and emits only aggregate public-safe
state.
```

## 8. Clarify Auth Disable Semantics

Avoid saying auth is simply "disabled" without qualification. The current design
temporarily disables the local CATS or AD preflight but places login attempts
into admin validation. A safer phrasing is:

```latex
Temporary CATS or AD disable does not automatically admit a student; it moves
the login into an operator-managed validation state with bounded approval time.
```

## 9. Tighten Security/Privacy Claims

The security section is strong, but it should explicitly say the projector is
privacy-safe by construction and excludes:

- login IDs
- UUIDs
- IP addresses
- process names
- window titles
- artifact paths
- submission paths
- evidence details

This is already true in the implementation and worth stating clearly.

## 10. Avoid Overclaiming Browser Control

For titlebar/browser monitoring, avoid wording that implies URL extraction or
tab-level control. The implementation is titlebar-based only.

Suggested phrasing:

```latex
Browser approval and violation handling are based on normalized window-title
patterns rather than URL extraction.
```

## 11. Mention Installer Package Safety

The final installer/deployment work should mention that dependencies are not
installed into machine-wide Python `site-packages`. This matters because
machine-wide pip installs can conflict with other software.

Suggested sentence:

```latex
The offline installer avoids global Python package pollution by installing
dependencies into a project-specific virtual environment and verifying bundled
payloads with a SHA-256 manifest where available.
```

## 12. Remove TODOs Before Submission

The current document still has TODO placeholders for several contributors and
for quantitative Results. Before final submission, remove or complete every
TODO block. Search for:

```text
TODO
```

## 13. Optional: Add A Short Requirements Traceability Sentence

Since the project now has SRS documentation, add a sentence in Requirements
Analysis:

```latex
The final SRS uses stable requirement identifiers such as \texttt{FR-SRV-*},
\texttt{FR-CLI-*}, \texttt{FR-INC-*}, and \texttt{NFR-SEC-*} to map
requirements to source modules and validation tests.
```

