# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Single-page Streamlit shopping list app (add / edit / delete / check items) in `app.py`, targeting Streamlit Community Cloud.

- `PRD.md` — requirements (Korean). Section numbers ("PRD 4.2", "PRD 10장") are used in tests and reports.
- `PROMPTS.md` — the staged plan the user follows (1 skeleton → 2 features → 3 UI → 4 Playwright review → 5 fix/deploy). Stay within the requested stage; stage 4 is report-only.
- Communicate with the user in Korean.

## Commands

```bash
pip install -r requirements.txt
streamlit run app.py

python -m pytest tests/ -p no:cacheprovider                      # all (unit + E2E)
python -m pytest tests/test_store.py                              # storage/validation unit tests, no browser
python -m pytest tests/test_app_e2e.py -k two_tabs -p no:cacheprovider   # single E2E test
```

E2E tests start their own Streamlit server on `APP_PORT` (default 8502, so a dev server on 8501 is unaffected) and back up / restore `data/shopping_list.json` — that file may hold the user's real data, never delete it. `-p no:cacheprovider` avoids a permission error writing `.pytest_cache` in this environment.

## Architecture

- **The store is the single source of truth.** No per-session copy of the list: `main()` calls `store().all()` every rerun and each mutation goes straight to the store. Earlier versions kept `st.session_state["items"]` and saved the whole list, which made concurrent tabs/users overwrite each other — don't reintroduce that.
- `store()` picks the backend: `SqlStore` (via `st.connection("shopping_db", type="sql")`) if `st.secrets["connections"]["shopping_db"]` exists, else `JsonStore` (`data/shopping_list.json`, read-modify-write under a `st.cache_resource` process-wide lock, atomic replace via unique temp file). Both expose `all / add / update / delete(item_ids=None, checked_only=False)`.
- PRD 8.3 functions (`load_items`, `save_items`, `add_item`, `update_item`, `delete_item`, `toggle_item`, `clear_checked`, plus `clear_all`) are thin wrappers over the store. `load_items` / `SqlStore.all` pass data through `normalize_items`, so malformed data never crashes rendering.
- `toggle_item(id, checked)` sets the value the user saw (checkbox widget state), not a blind flip, so stale tabs behave correctly. Checkbox state is re-synced from the store before each render (`st.session_state[f"chk_{id}"] = item["checked"]`).
- Optional `app_password` secret gates the app (`check_password`).

## Conventions

- Widget keys derive from item `id` (`chk_`, `edit_`, `del_`, `row_`, `edit_name_` …); tests and CSS select on these `st-key-*` classes.
- All state changes happen in `on_click`/`on_change` callbacks; messages are queued (`toasts`, `add_error`, `edit_error`) and rendered on the next run.
- User text rendered as markdown must go through `md_escape` (also escapes `:` to block Streamlit directives like `:red[...]`). The `CSS` block is static — never interpolate user input into it.
- `requirements.txt` pins `streamlit>=1.61` because the UI uses horizontal containers, `width=`, `text_alignment`, and badge markdown.
