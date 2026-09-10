# DEEPCRAFT&trade; Pull Request Tool

This repository ships **`pr_tool`**, a dependency-free Python CLI that helps
contributors open pull requests against Infineon DEEPCRAFT&trade; GitHub repos:

| `--repo` | Target |
| --- | --- |
| `accelerators` | [deepcraft-studio-accelerators](https://github.com/Infineon/deepcraft-studio-accelerators) |
| `model-zoo-psoc` | [deepcraft-model-zoo-for-psoc](https://github.com/Infineon/deepcraft-model-zoo-for-psoc) |

**End users:** see [`pr_tool/README.md`](pr_tool/README.md) for full usage,
options, project layouts, and troubleshooting.

**Requirements:** Python 3.10+, git 2.43+ (2.16.2+ on Windows), GitHub CLI
(bundled `pr_tool/gh.exe` or on `PATH`).

### Quick usage

From `pr_tool/`, run the tool against whichever target repo fits your project
and point `--path` at your project folder on disk:

```bash
cd pr_tool
python ./pr_tool.py --repo <target> --path <project-path>
```

Replace `<target>` with `accelerators` or `model-zoo-psoc`. The tool handles
GitHub auth, fork sync, branching, push, and opens the PR in your browser.

## File reference

| Path | Description |
| --- | --- |
| **`README.md`** | Maintainer guide (this file): architecture, extension points, testing, contributing. |
| **`.gitignore`** | Ignores local scratch, virtual environments, and OS artefacts. |
| **`scripts/parse_master_json.py`** | Fetches the DEEPCRAFT AI Hub `master.json` (or reads a local copy) and prints unique catalog values for `domain`, `application`, `use_case`, `kit`, `device`, and brand fields. Use the output to update `metadata/choices.py` manually. |
| **`pr_tool/README.md`** | End-user documentation: step-by-step usage, metadata behaviour, CLI flags, examples, troubleshooting. |
| **`pr_tool/pr_tool.py`** | Main entry point. Orchestrates project summary, metadata collection/review, git/gh setup, fork sync, sparse clone, chunked push, and PR creation. Validates registries at import time. |
| **`pr_tool/cli.py`** | `Cli` class wrapping `git` and `gh` subprocess calls. Resolves bundled vs system `gh`, enforces minimum git version, handles auth refresh, and prints commands when `--verbose` is set. |
| **`pr_tool/constants.py`** | Shared settings: `TARGET_REPOS` registry, git/GitHub defaults, UI icons, column padding for choice prompts. |
| **`pr_tool/target_repo.py`** | `TargetRepo` dataclass (repo name, PR title template, layout key, ignored push dirs) and registry validation against known layouts. |
| **`pr_tool/project_layouts.py`** | Project folder validators registered in `LAYOUTS` (accelerators vs model-zoo). |
| **`pr_tool/submission_exclusions.py`** | Git/Python paths excluded from layout checks and PR push (`pyvenv.cfg` / `conda-meta/` detection). |
| **`pr_tool/input.py`** | Argparse setup, `--repo` / `--path` / metadata CLI flags, and `Input.collect_metadata()` delegating to the metadata engine. |
| **`pr_tool/validation.py`** | Validates project layout and loaded `metadata.json` (missing fields, values outside AI Hub suggested lists with optional continue, derived-field repair). |
| **`pr_tool/image_selector.py`** | Loads `images.json`, exposes available tags/images, and picks the best tag overlap for auto-selection (fallback `deepcraft.webp`). |
| **`pr_tool/images.json`** | Shipped catalog of `{name, tags}` entries used for thumbnail/main image selection. |
| **`pr_tool/utils.py`** | `group_files()` splits diffs into push chunks under GitHub's ~2 GB and ~2,500-file limits; readonly cleanup helper for git scratch removal. |
| **`pr_tool/gh.exe`** | Bundled GitHub CLI for Windows (preferred over `PATH` when present). |
| **`pr_tool/LICENSE`** | License text for the tool distribution. |
| **`pr_tool/metadata/__init__.py`** | Public metadata API: `collect_metadata`, `finalize_metadata`, `format_metadata_json`, `get_metadata_schema`. |
| **`pr_tool/metadata/schema.py`** | `FieldSpec` and `MetadataSchema` types, field kinds, CLI flag registration per field. |
| **`pr_tool/metadata/schemas.py`** | Per-repo metadata schemas (`SCHEMAS`). Defines field order and composition for accelerators vs model-zoo (`_SHARED_FIELDS`, algorithm, links, metrics). |
| **`pr_tool/metadata/choices.py`** | Suggested values (sensors, domain, kit, …), brand definitions, kit→device and type→workflow mappings, and link builders for each repo. |
| **`pr_tool/metadata/engine.py`** | Walks the schema to collect metadata interactively: derived device/workflow, brand handling, link generation, schema-ordered output. |
| **`pr_tool/metadata/prompts.py`** | Interactive prompts (`input_str`, `input_choice`, `input_choices`, confirmations) including custom-value title-casing. |
| **`pr_tool/metadata/format.py`** | Pretty-prints `metadata.json` with keys in schema order. |
| **`pr_tool/metadata/image_field.py`** | Interactive and CLI-driven project image selection (`--image`, `--tag`, or pick from catalog). |

At startup, `pr_tool.py` checks that **`TARGET_REPOS` keys match `SCHEMAS`**
and that each target uses a registered **project layout**.

## Extending the tool

### How the pieces connect

```
constants.py              TARGET_REPOS   (--repo key → GitHub repo + layout)
       ↓
metadata/schemas.py       SCHEMAS        (same key → metadata.json fields)
       ↓
project_layouts.py        LAYOUTS        (layout name → folder rules)
submission_exclusions.py  filters        (git/Python artefacts → layout + push)
metadata/choices.py       tuples         (prompt suggestions + derivations)
```

`submission_exclusions.py` is separate from `project_layouts.py` and
`validation.py`: it defines which paths are ignored when validating the
accelerator project root and which paths are never committed or pushed (for
example `.git`, `__pycache__`, `.venv`, `*.pyc`). Virtual environments are
found by walking the tree for `pyvenv.cfg` or `conda-meta/`, not only by
folder name.

| Goal | Primary files |
| --- | --- |
| New `--repo` target | `constants.py`, `metadata/schemas.py`, `project_layouts.py` |
| Metadata fields / order | `metadata/schemas.py` |
| Choice lists, brands, links | `metadata/choices.py` |
| Sync lists from AI Hub | `scripts/parse_master_json.py` → copy into `choices.py` |
| Folder / name rules | `project_layouts.py` |
| Git/Python paths excluded from push | `submission_exclusions.py` |
| New field *kind* (rare) | `metadata/schema.py`, `engine.py`, `validation.py` |
| Git / PR flow | `pr_tool.py`, `cli.py` |

### Add a target repository

1. **`constants.py`** — add a `TargetRepo` to `TARGET_REPOS` (`key`, `repo_name`, `label`, `pr_title_template`, `project_layout`, `git_ignored_dirs`).
2. **`metadata/schemas.py`** — add a `MetadataSchema` with the same `repo_key`; register in `SCHEMAS`.
3. **`project_layouts.py`** — add or reuse a layout in `LAYOUTS`.

Keys in `TARGET_REPOS` and `SCHEMAS` must match 1:1 or the tool exits on startup.

### Add or change a metadata schema

Edit `metadata/schemas.py`. Fields are `FieldSpec(key, label, kind, …)`; **tuple order = `metadata.json` key order**.

| Kind | Role |
| --- | --- |
| `text`, `long_text` | Free text |
| `single_choice`, `multi_choice` | From `choices=`; optional `cli_flag` |
| `derived_workflow` | Auto from `type` |
| `image` / `image_mirror` | Thumbnail; mirror sets `main_image_id` |
| `brand` | Sets `brand_image_id` + `brand_url` |
| `accelerator_links`, `model_zoo_psoc_links` | Auto link arrays |
| `metrics` | Optional labelled metrics (model-zoo) |

### Update choice lists

Edit tuples in `metadata/choices.py`, or run `python scripts/parse_master_json.py` to list current AI Hub values and copy what you need. Update `KIT_TO_DEVICE` when adding kits; add `Brand` entries for new partners.

### Add a project layout

Subclass `ProjectLayout` in `project_layouts.py`, register in `LAYOUTS`, reference from `TargetRepo.project_layout`. For accelerators, root allow-list checks call `is_excluded_project_root_entry()` from `submission_exclusions.py` so git/Python artefacts do not fail validation.

### Change publish exclusions

Edit `EXCLUDED_NAMES` and `EXCLUDED_FILE_GLOBS` in `submission_exclusions.py`.
`pr_tool.py` uses `filter_submission_paths()` and `build_submission_exclude_pathspecs()` when building commits; layouts import only what they need for root checks.

## Testing locally

1. **Clone and optional venv**

   ```bash
   git clone <this-repo-url>
   cd deepcraft-studio-accelerators-pr-tool
   python -m venv .venv
   # Windows: .\.venv\Scripts\activate
   # macOS/Linux: source .venv/bin/activate
   ```

2. **Prepare a test project** on disk that matches the target layout:
   * **accelerators** — `README.md`, `metadata.json`, `<Name>.improj`, `Data/`; CamelCase name.
   * **model-zoo-psoc** — `README.md`, `metadata.json`; branch-safe folder name.

   A test folder may also be a local git repo or contain a venv; those paths are
   excluded from push and (for accelerators) from root layout validation.

3. **Run against your fork** (recommended so you do not open PRs against Infineon while developing):
   * Temporarily set `BASE_REPO_OWNER` in `constants.py` to your GitHub user/org.
   * Run from `pr_tool/` with verbose output:

     ```bash
     python ./pr_tool.py --repo <target> --path <test-project-path> -v
     ```

   * Confirm metadata, push, and PR creation behave as expected for your change.

4. **Revert test-only edits** (especially `BASE_REPO_OWNER`) before committing.

Use `-v` to see every `git` and `gh` command; that is the first place to look when something fails.

## Submitting changes to this repository

When you have modified the PR tool itself:

1. Create a feature branch from `main`.
2. Commit focused changes with a clear message (what and why).
3. Open a pull request against `main` of **this** repository (`deepcraft-studio-accelerators-pr-tool`), not the Infineon target repos.
4. In the PR description, summarise the change and how you tested it (target repo used, commands run, edge cases checked).
5. If you added a `--repo` target, new metadata fields, or layout rules, note any follow-up needed on the Infineon side (catalog updates, hub changes, etc.).

## License

See the upstream Infineon target repositories for licensing of published content.
