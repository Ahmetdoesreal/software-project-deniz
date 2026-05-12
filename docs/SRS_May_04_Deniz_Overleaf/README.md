# May_04_Deniz SRS Package

This folder contains a Software Requirements Specification package for the current
`May_04_Deniz` implementation. It is designed for two workflows:

- Markdown review and editing inside the repository.
- Direct Overleaf upload/compile using the `.tex` files in `overleaf/`.

## Files

| File | Purpose |
| --- | --- |
| `full_project_srs.md` | Whole-project SRS for the complete server, client, GUI, IPC, monitoring, incident, authentication, projector, submission, and installer system. |
| `my_parts_srs.md` | Contributor-focused SRS copy for the project parts most likely to be presented as an individual implementation contribution. |
| `overleaf/main_full_project_srs.tex` | Overleaf-compatible LaTeX version of the whole-project SRS. |
| `overleaf/main_my_parts_srs.tex` | Overleaf-compatible LaTeX version of the contributor-focused SRS copy. |

## Overleaf Usage

1. Create a new blank Overleaf project.
2. Upload either `main_full_project_srs.tex` or `main_my_parts_srs.tex`.
3. Set the uploaded file as the main document if Overleaf does not detect it automatically.
4. Compile with pdfLaTeX. No shell escape, external images, or minted package is required.

The LaTeX files intentionally use only common packages such as `geometry`,
`hyperref`, `longtable`, `array`, `enumitem`, and `fancyhdr` so that they compile
on standard Overleaf installations.

## Source Baseline

The documents are based on:

- `May_04_Deniz/`
- `docs/FINAL_REPORT_May_04_Deniz/`
- current automated validation status from the latest local test run

Older snapshots are not treated as authoritative except as historical context.

