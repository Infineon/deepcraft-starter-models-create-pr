# ── Git & GitHub ─────────────────────────────────────────────
HOST = 'https://github.com'
BASE_REPO_OWNER = 'Infineon'
MAIN_BRANCH = 'main'
GIT_DIR = '.git_deepcraft'
MINIMUM_UPDATABLE_GIT_VERSION = '2.16.2'  # update-git-for-windows option
MINIMUM_GIT_VERSION = '2.43'  # git show-ref --exists
# Split large pushes before hitting GitHub's ~2 GB / push soft limit and the
# ~3,000-file PR file list. Keep commits smaller so staging/push/PR create stay reliable.
GH_PUSH_MAX_BYTES = (2 * 1024 * 1024 * 1024) - 1
GH_PUSH_MAX_FILES = 2500

# ── Self-update ──────────────────────────────────────────────
# Public GitHub repository hosting this tool; used to fetch newer versions.
TOOL_REPO = 'Infineon/deepcraft-studio-accelerators-pr-tool'

# Use in terminal output (print). README files use HTML ``&trade;`` instead.
DEEPCRAFT = 'DEEPCRAFT\u2122'

# ── Target Repositories ─────────────────────────────────────────
from target_repo import TargetRepo

TARGET_REPOS: dict[str, TargetRepo] = {
    'accelerators': TargetRepo(
        key='accelerators',
        repo_name='deepcraft-studio-accelerators',
        label=f'{DEEPCRAFT} Studio Accelerators',
        pr_title_template='Accelerator {project_name}',
        project_layout='accelerator_layout',
        git_ignored_dirs=('Models', 'PreprocessorTrack'),
    ),
    'model-zoo-psoc': TargetRepo(
        key='model-zoo-psoc',
        repo_name='deepcraft-model-zoo-for-psoc',
        label=f'{DEEPCRAFT} Model Zoo for PSOC',
        pr_title_template='Model Zoo PSOC {project_name}',
        project_layout='model_zoo_psoc_layout',
        git_ignored_dirs=(),
    ),
}

# ── UI ───────────────────────────────────────────────────────
COLUMN_PADDING = 2  # spaces between columns in numbered-choice prompts

ICON_PULL_REQUEST = '🔀'  # main banner — submit / merge a pull request
ICON_SUCCESS = '✅'
ICON_ERROR = '❌'
ICON_WARNING = '⚠️'
ICON_INFO = 'ℹ️'
ICON_PROGRESS = '▶️'
ICON_ABORT = '🛑'
