# DEEPCRAFT&trade; Pull Request Tool

A small Python command-line utility for opening pull requests against Infineon
DEEPCRAFT&trade; GitHub repositories:

* [Infineon/deepcraft-studio-accelerators](https://github.com/Infineon/deepcraft-studio-accelerators) (`--repo accelerators`)
* [Infineon/deepcraft-model-zoo-for-psoc](https://github.com/Infineon/deepcraft-model-zoo-for-psoc) (`--repo model-zoo-psoc`)

The tool wraps `git` and the bundled GitHub CLI (`pr_tool/gh.exe`) to automate the whole workflow
for you:

1. Authenticates using your GitHub account.
2. Forks the selected Infineon repository to your account (or syncs an existing fork).
3. Creates / switches to a branch named after your project.
4. Commits and pushes your project's files (splitting large change sets into
   chunks under GitHub's ~2 GB per-push limit and about 2,500 files per
   commit, so large Data folders stay reliable).
5. Opens the resulting pull request in your browser.

The same command can also be used to **update** an existing pull request &ndash;
just re-run it after making changes to your project.

## Requirements

* **Python 3.10** or newer
* **git 2.43** or newer
  * On Windows, git 2.16.2+ is also accepted &mdash; the tool will run
    `update-git-for-windows` automatically to bring it up to date.
* **GitHub CLI** (`gh`) &mdash; the copy **bundled** as `pr_tool/gh.exe` is used
  when present; otherwise `gh` on your `PATH`. Each binary has its own login
  (install from [cli.github.com](https://cli.github.com/) if needed).
* A **GitHub account**

No additional Python packages are required &mdash; the tool only uses the
standard library.

Project image names and tags are read from **`pr_tool/images.json` only**
(shipped with the tool). The catalog is not downloaded from the network.

## Target repositories (`--repo`)

| `--repo` value | GitHub repository | Project layout |
| --- | --- | --- |
| `accelerators` | `Infineon/deepcraft-studio-accelerators` | `accelerator_layout` (DEEPCRAFT&trade; Studio, below) |
| `model-zoo-psoc` | `Infineon/deepcraft-model-zoo-for-psoc` | `model_zoo_psoc_layout` (README + metadata only) |

Every layout requires **`README.md`** and **`metadata.json`** at the project root.
Metadata is collected the same way for both repositories.

The `--repo` argument is **required** on every run.

## Project layout requirements (`--repo accelerators`)

Before running the tool for **accelerators**, make sure your project directory has the following
layout. The tool validates this before doing anything.

**Required items** (must be present at the project root):

* `README.md`
* `metadata.json`
* `<ProjectName>.improj`
* `Data/`

**Allowed items** (optional, may be present):

* `*.im*` files (other DEEPCRAFT&trade; Studio files)
* `Models/`
* `PreprocessorTrack/`
* `Resources/`
* `Tools/`
* `Units/`

Anything else at the project root will cause the tool to fail with a clear
error message (see [Local git and Python environments](#local-git-and-python-environments)).
Folder and file names are **case-sensitive** and must match exactly
(e.g. `Models/`, not `models/`; `Data/`, not `data/`).
The `Models/` and `PreprocessorTrack/` directories are tracked
in your project but are **not** pushed to GitHub.

The project name **defaults to the project folder's name** and is used as
both the **branch name** and the **PR title prefix** on GitHub (e.g.
`Accelerator MyAudioClassifier`). It must be in **CamelCase**, e.g.
`MyAudioClassifier`. You can override it with `--name <CamelCaseName>` if
the folder name doesn't match the desired project name.

## Project layout requirements (`--repo model-zoo-psoc`)

For the [Model Zoo for PSOC](https://github.com/Infineon/deepcraft-model-zoo-for-psoc),
the project folder must include **`README.md`** and **`metadata.json`** at its
root. Other files and folders at the root are allowed (for example deployment
code, HEX files, or model assets).

The project name defaults to the project folder name and is used as the
**branch name** on GitHub (for example `ArcFace`, `Yolov8nPose`, or
`EfficientNetV2-S`). It must be safe for a **local folder name and a Git branch**:
letters, digits, `.`, `_`, and `-` are allowed; it must start and end with a
letter or digit; **spaces are not allowed** (and characters such as `\ / : * ? "
< > | ~ ^ [` are rejected).

## Local git and Python environments

Your project folder may already be a git repo or contain a Python virtual
environment. That is fine: local git data, virtualenvs, and typical Python
cache folders are **not** uploaded. With `--repo accelerators`, they are also
ignored when the tool checks the project root layout.

## Usage

From the directory containing `pr_tool.py`, run:

```bash
python ./pr_tool.py --repo <target> --path <project-path>
```

`<target>` is `accelerators` or `model-zoo-psoc`. `<project-path>` is the
root of your project folder.

The first time you run the tool you will be:

1. Prompted to authenticate with GitHub in your browser (only once &ndash;
   credentials are then cached by `gh`).
2. Shown a **project summary** and asked to confirm before continuing.
3. Asked for **metadata** (unless `metadata.json` already exists and you did
   not pass `--override-metadata`). A few fields can be set via CLI flags on
   the first pass; the rest are prompted interactively.

When metadata is ready, the tool shows a preview and asks:

* **y** &ndash; accept and proceed (`metadata.json` is saved immediately,
  before any git or GitHub steps).
* **n** &ndash; re-enter metadata (previous values are kept as defaults).
* **a** &ndash; abort without saving.

When the push completes, the tool creates or reuses the pull request, waits
until GitHub exposes it (up to about 5 minutes), then opens it in the browser
and prints the PR URL. If that automatic step fails (common right after very
large pushes), your project is usually already on the fork — open your fork or
the Infineon repo in the browser; GitHub typically shows a banner with a
**Compare & pull request** button. The tool also prints those links (plus a
direct compare URL) so you can finish in a click without reading raw ``gh``
errors.

### Interactive metadata

Suggested values for list fields (sensors, domain, kit, …) come from the
DEEPCRAFT&trade; AI Hub catalog. Prompt order matches the metadata schema for
your selected `--repo`.

| Topic | Behaviour |
| --- | --- |
| **Choices** (sensors, domain, kit, …) | Pick by number from the AI Hub list, or type a custom value (one confirmation). Custom text is title-cased (`smart home` → `Smart Home`). |
| **Kit → device** | Device is derived from kit(s); custom kit names prompt for device. |
| **Type → workflow** | Pick one or both types (`1,2`); workflow is set automatically. |
| **Brand** | Infineon, a listed partner, or **New Brand/Partner** (custom image + URL). |
| **Links** | Filled automatically (accelerators: Studio + GitHub; model-zoo: GitHub). |
| **Image** | Auto-pick from `images.json` by tags, or choose interactively. `--image` / `--tag` skip the prompt. |
| **Accelerators only** | `algorithm` required. |
| **Model zoo only** | `metrics` optional (fixed labels, you enter values). |

All fields are required except `metrics` on `model-zoo-psoc`.

If **`metadata.json` already exists**, the tool loads it first: missing fields
are prompted; values not in the AI Hub–based suggested lists show a warning
(this is normal for new projects with sensors, kits, or devices not yet in the
catalog, or if the file was edited or is outdated). You can continue, edit
`metadata.json`, or re-run with `--override-metadata`.

### Updating an existing pull request

To push new changes to a pull request you already opened, **just re-run the
exact same command on the same project folder**:

```bash
python ./pr_tool.py --repo <target> --path <project-path>
```

What happens under the hood:

1. The branch name is taken from the project name (which defaults to the
   project folder's name), so a second run resolves to the same branch as the
   first run.
2. The tool sees that branch already exists on your fork and switches to it
   instead of creating a new one. Commit messages change from `Add files` /
   `Add chunk N of M` to `Modify files` / `Modify chunk N of M` on subsequent
   runs.
3. Only the diff against your previous push is committed and pushed (file
   additions, modifications, and deletions are all handled).
4. If a pull request is already **open** for that branch, the tool simply
   **opens it in your browser** &ndash; no new PR is created.

Things to watch out for:

* **Don't rename the project folder between runs** (or, if you must, pass
  `--name <SameCamelCaseName>` explicitly). Otherwise the tool will use a
  different branch and open a **new** pull request alongside the old one.
* **If the pull request was closed or merged on GitHub**, the next run asks
  whether to keep the existing fork branch or reset it and start fresh from
  the current upstream `main`. Keeping the branch is the safe choice when you
  want to preserve its history; resetting it is useful when you want a clean
  PR without old branch history. An **open** PR is left alone and just opened
  in the browser.
* **Changing metadata on a subsequent run** &ndash; edit `metadata.json`
  directly and re-run (changes are pushed like any other file), or use
  `--override-metadata` to regenerate it interactively.

### The `.git_deepcraft` folder

While the tool runs it creates a working directory next to your project:

```
<project-path>/..
├── <ProjectName>/              <- your DEEPCRAFT&trade; Studio project
└── .git_deepcraft/
    └── <repo-key>/             <- e.g. accelerators, model-zoo-psoc
        └── <ProjectName>/      <- git metadata for this project's PR
```

This folder is the tool's separate **git directory** &mdash; it stores all of
git's bookkeeping (objects, refs, branches, remote configuration) for the
pull request, **without** placing a `.git` folder inside your project itself.
That keeps your project directory clean and avoids interfering with any
existing version control you may have there.

Each project uses `.git_deepcraft/<repo-key>/<ProjectName>/`. If you run the
tool for several projects at the same time, each keeps its own subfolder until
that run finishes.

**What happens if you delete it?**

* **After a run:** the tool removes this project's scratch folder and, when
  nothing else is using `.git_deepcraft`, removes the whole `.git_deepcraft`
  directory. The next run recreates it by cloning your fork freshly.
* **Between runs:** deleting it manually is harmless for the same reason.
* **During a run:** the current run will fail, because git can no longer find
  its metadata. Simply re-run the command &mdash; the folder will be
  recreated from scratch.
* **Your pull request is not affected.** All commits already live on GitHub
  (in your fork and on the PR). `.git_deepcraft` is purely local scratch
  space; deleting it never loses any work that has been pushed.

### Common options

| Option | Description |
| --- | --- |
| `--repo <target>` | **Required.** `accelerators` or `model-zoo-psoc` (see table above). |
| `--path <project-path>` | **Required.** Root directory of your project. |
| `--name <CamelCaseName>` | Override the project name (defaults to the directory name). Also becomes the branch name on GitHub. |
| `--title <text>` | Project title (max 40 characters). |
| `--description <text>` | Short project description (max 100 characters). |
| `--algorithm <name>` | Accelerators only. `Classification`, `Regression`, or `Object Detection`. |
| `--sensor <name>` | Target sensor. Run `--help` to see the suggested list. Can be passed multiple times (e.g. `--sensor Microphone --sensor Camera`) to specify more than one sensor. |
| `--image <name>` | Image name to use directly (e.g. `Audio.webp`). Skips the tag-based auto-selection and the interactive image prompt. |
| `--tag <tag>` | Tag used to auto-pick a project image. Can be passed multiple times (e.g. `--tag audio --tag "smart home"`). Skips the interactive image prompt but not the auto-selection step. Not saved to `metadata.json`. |
| `--override-metadata` | Regenerate `metadata.json` from the options above even if one already exists. |
| `--verbose`, `-v` | Print every `git`/`gh` command and captured output (default is short progress lines only). |

For the complete list of options, run:

```bash
python ./pr_tool.py --help
```

### Example

Single sensor:

```bash
python ./pr_tool.py \
  --repo accelerators \
  --path C:\Projects\MyAudioClassifier \
  --title "My audio classifier" \
  --description "Detects three types of household sounds" \
  --algorithm Classification \
  --sensor Microphone
```

With a specific image (skips the image prompt entirely):

```bash
python ./pr_tool.py \
  --repo accelerators \
  --path C:\Projects\MyMultiModalDetector \
  --title "Multi-modal detector" \
  --description "Combines audio and motion signals" \
  --algorithm Classification \
  --sensor Microphone \
  --sensor IMU \
  --image Motion.webp
```

With tags for auto-selection (skips the image prompt, auto-picks the best
match):

```bash
python ./pr_tool.py \
  --repo accelerators \
  --path C:\Projects\MyMultiModalDetector \
  --title "Multi-modal detector" \
  --description "Combines audio and motion signals" \
  --algorithm Classification \
  --sensor Microphone \
  --sensor IMU \
  --tag audio \
  --tag motion
```

Model Zoo for PSOC:

```bash
python ./pr_tool.py \
  --repo model-zoo-psoc \
  --path C:\Projects\ArcFace \
  --title "ArcFace" \
  --description "Face recognition model for PSOC" \
  --sensor Camera
```

## Troubleshooting

* **`git version 2.43 or newer is required`** &mdash; install / update git
  from [git-scm.com](https://git-scm.com/). On Windows, the tool will try
  `update-git-for-windows` first.
* **`GitHub CLI (gh) not found`** &mdash; make sure `gh.exe` is present in the
  `pr_tool/` folder next to `pr_tool.py`, or install the GitHub CLI from
  [cli.github.com](https://cli.github.com/) and add it to your `PATH`. At
  startup the tool prints which `gh` binary it is using.
* **`Project name "..." is not CamelCase`** &mdash; with `--repo accelerators`,
  rename the project directory (or pass `--name`) to CamelCase (e.g.
  `MyAudioClassifier`).
* **Invalid project name (Model Zoo)** &mdash; with `--repo model-zoo-psoc`, the
  name must be folder- and branch-safe: no spaces; use letters, digits, `.`,
  `_`, or `-`; start and end with a letter or digit (e.g. `EfficientNetV2-S`).
* **`Items {...} are missing` / `not allowed in project's root directory`**
  &mdash; adjust your project root so it matches the layout described in
  [Project layout requirements](#project-layout-requirements-repo-accelerators)
  (`--repo accelerators` only). Git and Python artefacts are excluded; see
  [Local git and Python environments](#local-git-and-python-environments).
* **Authentication issues** &mdash; the tool prefers bundled `pr_tool/gh.exe`
  (each `gh` binary keeps its own login).
  Run `gh auth status` with the same binary shown at startup. If you are logged
  in but missing permissions, the tool runs `gh auth refresh` for the
  `workflow` scope instead of asking for a full login when possible. If the
  token is invalid, run `gh auth login -h github.com` for that binary.
* **Your fork is out of sync** &mdash; the tool tries to sync your fork's
  `main` with Infineon. If that fails, it asks before deleting and recreating
  the entire fork (which would remove all other branches on that fork). It will
  also prompt to grant the `delete_repo` scope when recreation is confirmed.

By default the tool prints short progress lines, a simple progress bar while
staging/pushing, and an animated status spinner during long waits (clone,
branch switch, scanning large folders). For full command output, run with
`--verbose` (or `-v`); that prints every `git` and `gh` command and is the
first place to look when something goes wrong.
