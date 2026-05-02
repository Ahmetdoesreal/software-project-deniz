# File Classification

Classification values:
- `required`: included in `near final delivery` and part of production runtime/validation.
- `optional-candidate`: not required for baseline runtime, can be added later by profile choice.
- `archive`: excluded from this delivery base.

## Required (copied)
- `client/`
- `server/`
- `common/`
- `custommodules/`
- `tests/`
- `requirements.txt`
- `setup.py`
- `server_cli.py`
- `client_cli.py`
- `run_demo.py`
- `run_demo.bat`
- `run_demo.sh`
- `allowed_users.json`
- `client_gui.py`
- `server_gui.py`
- `client_launcher.py`
- `server_launcher.py`

## Optional-Candidate (not copied)
- `clean_runtime.py` (cleanup helper; not part of runtime hot path)
- `ui_preview.py` (preview utility)
- `tools/runtime_timeline_viewer/*` (analysis/visualization utility)
- `TEMPLATE_new_event.py` (template, not runtime)
- `mytask_workspace/*` (focused workspace copy)
- `mytask_files/*` (task reference text)
- `docs/discovery_v2_analysis.md`
- `docs/client_monitoring_report.md`

## Archive (excluded)
- `third_iteration/`
- `clean_iteration/`
- `extras_new/`
- `legacy/`
- `to-be-implemented/`
- `deliver_to_baris/`
- `deliver_to_baris_ahmet_only/`
- `baris_files/`
- `ayrilan_dosyalar/`
- `docs/*.docx`
- `docs/*.pages`
- `docs/*.pdf`
- `*.ipynb` outside required runtime/test paths
- runtime/generated folders outside delivery base (for example `data/` in source root)
