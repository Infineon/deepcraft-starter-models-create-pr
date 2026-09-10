import json
import os
import shutil
import sys
import time
from pathlib import Path
from subprocess import PIPE, CalledProcessError, DEVNULL
from tempfile import NamedTemporaryFile, TemporaryDirectory

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from cli import (
    Cli,
    called_process_error_text,
    is_network_error,
    print_network_failure,
)
from constants import (
    BASE_REPO_OWNER,
    GIT_DIR,
    GH_PUSH_MAX_BYTES,
    GH_PUSH_MAX_FILES,
    HOST,
    ICON_ABORT,
    ICON_ERROR,
    ICON_INFO,
    ICON_PROGRESS,
    ICON_PULL_REQUEST,
    ICON_SUCCESS,
    ICON_WARNING,
    DEEPCRAFT,
    MAIN_BRANCH,
    TARGET_REPOS,
)
from input import Input, confirm
from updater import ensure_latest_version
from metadata import confirm_metadata, finalize_metadata, format_metadata_json, get_metadata_schema
from submission_exclusions import (
    build_submission_exclude_pathspecs,
    filter_submission_paths,
)
from target_repo import validate_target_repos_registry
from utils import group_files
from project_layouts import on_disk_names_matching
from validation import validate_loaded_metadata, validate_project_structure
from metadata.schemas import validate_metadata_schemas


def onerror(func, path, exc_info):
    import stat
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise


def cleanup_git_scratch(git_dir: Path) -> None:
    """Remove separate-git-dir scratch and any now-empty parent folders up to .git_deepcraft."""
    if git_dir.exists():
        shutil.rmtree(git_dir, onerror=onerror)
    current = git_dir.parent
    while current.name != GIT_DIR:
        if not current.exists() or any(current.iterdir()):
            return
        current.rmdir()
        current = current.parent
    if current.exists() and not any(current.iterdir()):
        current.rmdir()


def cleanup_git_scratch_with_progress(git_dir: Path) -> None:
    """Remove scratch dir, showing a spinner so large cleanups do not look hung."""
    if not git_dir.exists():
        return
    # After multi-chunk pushes the local object store can be huge; deleting it on
    # Windows often takes minutes with no other output — always tell the user.
    try:
        with cli.busy(
            'Cleaning up temporary git workspace '
            '(can take a few minutes after large pushes)',
        ):
            cleanup_git_scratch(git_dir)
    except KeyboardInterrupt:
        print()
        print(f'  {ICON_WARNING} Cleanup interrupted. You can delete this folder manually:')
        print(f'       {git_dir}')
        print(f'  {ICON_INFO} Or delete the whole "{GIT_DIR}" folder next to your project.')
        print()
        raise


def reset_git_scratch(git_dir: Path) -> None:
    """Remove a partial scratch dir so a network retry can clone into a clean tree."""
    if git_dir.exists():
        shutil.rmtree(git_dir, onerror=onerror)
    git_dir.parent.mkdir(parents=True, exist_ok=True)


def offer_network_retry(action: str, exc: BaseException) -> bool:
    """Explain a connectivity failure and ask whether to retry. Return True to retry."""
    if isinstance(exc, CalledProcessError):
        detail = called_process_error_text(exc)
    else:
        detail = str(exc)
    if not is_network_error(detail) and not is_network_error(str(exc)):
        return False
    print_network_failure(action, detail)
    return confirm('Retry connecting to GitHub?')


def should_reset_branch(pr_state: str, branch_name: str) -> bool:
    """Ask whether to replace a merged/closed fork branch with a fresh one from main."""
    print()
    print('=' * 60)
    print(f'  {ICON_WARNING} A previous PR for branch "{branch_name}" is {pr_state.lower()}.')
    print('=' * 60)
    print(f'  {ICON_INFO} Keep the existing fork branch to preserve its history, or')
    print('  reset it to start fresh from the current upstream main branch.')
    print(f'  {ICON_WARNING} Resetting deletes and recreates this branch on your fork.')
    print('=' * 60)
    print()
    return confirm('Start a fresh branch from main?')


def fork(base_repo: str) -> None:
    gh(['repo', 'fork', base_repo, '--default-branch-only'])
    time.sleep(2)  # Wait for repo to be created


def _is_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(c in '0123456789abcdef' for c in value.lower())


def ensure_fork_matches_upstream(user, target_repo) -> None:
    """`gh repo sync --force` can leave the fork ahead of upstream (stale merge commits).

    Compare the fork's and upstream's main SHA and force-reset the fork's ref via the
    GitHub API when they differ, so the project branch is created from a clean base.
    """
    upstream_sha = gh(['api', f'repos/{target_repo.base_repo}/commits/{MAIN_BRANCH}',
                       '--jq', '.sha'], check=False)
    fork_sha = gh(['api', f'repos/{user}/{target_repo.repo_name}/commits/{MAIN_BRANCH}',
                   '--jq', '.sha'], check=False)
    if not _is_commit_sha(upstream_sha) or not _is_commit_sha(fork_sha):
        print()
        print('=' * 60)
        print(f'  {ICON_ERROR} Could not verify that your fork main matches Infineon.')
        print('=' * 60)
        print(f'  {ICON_INFO} Check network access to GitHub and re-run the tool.')
        print('=' * 60)
        print()
        sys.exit(1)
    if upstream_sha == fork_sha:
        return
    cli.progress('Fork still ahead of upstream; resetting fork main to upstream...')
    patch_rc = gh(['api', '-X', 'PATCH',
                   f'repos/{user}/{target_repo.repo_name}/git/refs/heads/{MAIN_BRANCH}',
                   '-f', f'sha={upstream_sha}', '-F', 'force=true'], check=False)
    if patch_rc != 0:
        print()
        print('=' * 60)
        print(f'  {ICON_ERROR} Failed to reset fork main to Infineon main.')
        print('=' * 60)
        print(f'  {ICON_INFO} Re-run the tool, or sync the fork manually on GitHub.')
        print('=' * 60)
        print()
        sys.exit(1)
    fork_sha_after = gh(['api', f'repos/{user}/{target_repo.repo_name}/commits/{MAIN_BRANCH}',
                         '--jq', '.sha'], check=False)
    if fork_sha_after != upstream_sha:
        print()
        print('=' * 60)
        print(f'  {ICON_ERROR} Fork main still does not match Infineon after reset.')
        print('=' * 60)
        print(f'  {ICON_INFO} Re-run the tool, or sync the fork manually on GitHub.')
        print('=' * 60)
        print()
        sys.exit(1)


def print_header(title: str, *, icon: str = '') -> None:
    sep = '=' * 60
    label = f'{icon} {title}' if icon else title
    print(f'\n{sep}')
    print(f'  {label}')
    print(sep)


def looks_like_url(value: str) -> bool:
    return isinstance(value, str) and (value.startswith('http://') or value.startswith('https://'))


def _usable_gh_string(value: object) -> str | None:
    """Return a non-empty gh --jq string, or None when missing/failed."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    # jq prints the JSON null literal when the field is absent.
    if not text or text == 'null':
        return None
    return text


def resolve_git_identity(user: str) -> tuple[str, str]:
    """Return ``(name, email)`` for ``git config user.*``.

    GitHub often hides the account email; fall back to the noreply address so
    commits never fail for lack of identity on a clean machine.
    """
    api_name = _usable_gh_string(gh(['api', 'user', '--jq', '.name'], check=False))
    api_email = _usable_gh_string(gh(['api', 'user', '--jq', '.email'], check=False))
    return api_name or user, api_email or f'{user}@users.noreply.github.com'


def wait_for_pull_request_url(
    head_branch: str,
    *,
    timeout_s: int = 300,
    interval_s: int = 10,
) -> str | None:
    """Poll until ``gh pr view`` returns a URL, or until *timeout_s* elapses."""
    deadline = time.time() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        url = _usable_gh_string(
            gh(
                ['pr', 'view', head_branch, '--json', 'url', '--jq', '.url'],
                check=False,
                quiet_stderr=True,
            ),
        )
        if looks_like_url(url or ''):
            if attempt > 1:
                cli.progress_bar(timeout_s, timeout_s, 'Pull request is ready', final=True)
            return url
        remaining = int(deadline - time.time())
        if remaining <= 0:
            if attempt > 1:
                cli.progress_bar(timeout_s, timeout_s, 'Timed out waiting for PR', final=True)
            return None
        elapsed = max(0, timeout_s - remaining)
        cli.progress_bar(
            elapsed,
            timeout_s,
            f'Waiting for GitHub to prepare the PR (attempt {attempt})...',
        )
        wait_for = min(interval_s, max(1, remaining))
        time.sleep(wait_for)


def recreate_fork_with_confirmation(user: str, target_repo) -> None:
    """Delete and re-fork only after an explicit yes — this wipes all fork branches."""
    print()
    print('=' * 60)
    print(f'  {ICON_WARNING} Could not sync your fork\'s main branch with Infineon.')
    print('=' * 60)
    print(f'  {ICON_WARNING} Recreating the fork DELETES the entire repository')
    print(f'  {user}/{target_repo.repo_name} on your account, including every')
    print('  other project branch and unmerged work on that fork.')
    print(f'  {ICON_INFO} Prefer fixing network/permissions and re-running if you')
    print('  have other work on this fork.')
    print('=' * 60)
    print()
    if not confirm('Delete and recreate your entire fork?'):
        print(f'{ICON_ABORT} Aborted — fork was not deleted.')
        print(f'  {ICON_INFO} Re-run the tool later, or sync the fork manually on GitHub.')
        sys.exit(0)
    cli.progress('Recreating fork...')
    gh(['auth', 'refresh', '--hostname', 'github.com', '-s', 'workflow,delete_repo'])
    gh(['repo', 'delete', f'{user}/{target_repo.repo_name}', '--yes'])
    fork(target_repo.base_repo)


def ensure_remote_branch_for_pr(
    *,
    branch_is_new: bool,
    pushed_changes: bool,
    branch_name: str,
) -> bool:
    """Return False when a new local branch was never pushed (PR head would be missing)."""
    if pushed_changes or not branch_is_new:
        return True
    print()
    print('=' * 60)
    print(f'  {ICON_ERROR} Nothing to push, and branch "{branch_name}" is not on your fork yet.')
    print('=' * 60)
    print(f'  {ICON_INFO} A pull request cannot be created until the branch exists')
    print('  on GitHub with at least one commit that differs from main.')
    print(f'  {ICON_INFO} Make sure your project has content to submit, then re-run.')
    print('=' * 60)
    print()
    return False


def stage_paths_with_progress(
    paths: list[str],
    *,
    label: str,
    batch_size: int = 400,
) -> None:
    """``git add`` *paths*, updating a progress bar for large batches."""
    total = len(paths)
    if total == 0:
        return
    if total <= batch_size:
        cli.progress(f'Staging {label} ({total} file{"s" if total != 1 else ""})...')
        with NamedTemporaryFile('w', delete=False) as pathspec:
            pathspec.write('\n'.join(paths))
            pathspec.close()
            git(['add', f'--pathspec-from-file={pathspec.name}'])
            os.remove(pathspec.name)
        return

    cli.progress_bar(0, total, f'Staging {label}...')
    for start in range(0, total, batch_size):
        chunk = paths[start:start + batch_size]
        with NamedTemporaryFile('w', delete=False) as pathspec:
            pathspec.write('\n'.join(chunk))
            pathspec.close()
            git(['add', f'--pathspec-from-file={pathspec.name}'])
            os.remove(pathspec.name)
        done = min(total, start + len(chunk))
        cli.progress_bar(
            done,
            total,
            f'Staging {label}...',
            final=(done >= total),
        )


def _pr_compare_url(head_branch: str, target_repo) -> str:
    """GitHub compare URL to open a PR from *head_branch* into Infineon main."""
    return (
        f'{HOST}/{target_repo.base_repo}/compare/{MAIN_BRANCH}...{head_branch}'
        f'?expand=1'
    )


def _fork_url(user: str, target_repo) -> str:
    return f'{HOST}/{user}/{target_repo.repo_name}'


def _upstream_url(target_repo) -> str:
    return f'{HOST}/{target_repo.base_repo}'


def print_manual_pr_next_steps(user: str, head_branch: str, target_repo) -> None:
    """Tell the user how to finish the PR on GitHub when the tool could not open it."""
    fork_url = _fork_url(user, target_repo)
    upstream_url = _upstream_url(target_repo)
    print(f'  {ICON_INFO} Your project was pushed to your fork. Finish the PR in the browser:')
    print()
    print(f'  1. Open your fork:')
    print(f'       {fork_url}')
    print(f'     or open Infineon\'s repo:')
    print(f'       {upstream_url}')
    print()
    print(f'  2. Near the top of the page, GitHub usually shows a banner about')
    print(f'     recent pushes, with a green "Compare & pull request" button.')
    print(f'     Click that button, review the form, and create the pull request.')
    print()
    print(f'  3. If you do not see the banner yet, wait a minute and refresh')
    print(f'     (large pushes can take a while to appear), or use this link:')
    print(f'       {_pr_compare_url(head_branch, target_repo)}')
    print()
    print(f'  {ICON_INFO} Re-running this tool later is also safe.')


def open_or_create_pull_request(
    head_branch: str,
    project_name: str,
    target_repo,
) -> str | None:
    """Create or reuse a PR, poll until a URL is available, then open the browser.

    Returns the PR URL on success, or ``None`` when creation/lookup failed.
    Expected ``gh`` misses (no PR yet) do not dump raw CLI help to the user.
    """
    print()
    print('=' * 60)
    print(f'  {ICON_INFO} Push to your fork finished.')
    print(f'  {ICON_INFO} Next: create or open the pull request on Infineon.')
    print('=' * 60)
    print()

    cli.progress('Checking for an existing open pull request...')
    pr_state = _usable_gh_string(
        gh(
            ['pr', 'view', head_branch, '--json', 'state', '--jq', '.state'],
            check=False,
            quiet_stderr=True,
        ),
    )

    if pr_state == 'OPEN':
        cli.progress('Open PR found. Confirming it with GitHub...')
    else:
        cli.progress('No open PR yet. Creating one (this can take a while for large pushes)...')
        # Do not pass --web here: open only after the URL is confirmed ready.
        create_rc = gh([
            'pr', 'create',
            '--base', MAIN_BRANCH,
            '--head', head_branch,
            '--title', target_repo.pr_title(project_name),
        ], check=False, quiet_stderr=True)
        if create_rc != 0:
            immediate = _usable_gh_string(
                gh(
                    ['pr', 'view', head_branch, '--json', 'url', '--jq', '.url'],
                    check=False,
                    quiet_stderr=True,
                ),
            )
            if not looks_like_url(immediate or ''):
                print()
                print(f'  {ICON_ERROR} Could not create the pull request automatically.')
                print(f'  {ICON_INFO} Your project may already be on the fork — see next steps below.')
                print()
                return None
            cli.progress('PR create reported an issue, but a PR URL is already available...')

    print(f'  {ICON_INFO} Waiting for GitHub to expose the PR (up to ~5 minutes).')
    print(f'  {ICON_WARNING} Stay here — the tool will open the browser when ready.')
    print()
    pr_url = wait_for_pull_request_url(head_branch)
    if looks_like_url(pr_url or ''):
        cli.progress('Opening pull request in browser...')
        gh(['pr', 'view', head_branch, '--web'], check=False, quiet_stderr=True)
        return pr_url

    print()
    print(f'  {ICON_WARNING} Timed out waiting for GitHub to expose the PR URL.')
    print(f'  {ICON_INFO} Your project may already be on the fork — see next steps below.')
    print()
    return None


# ── Tool start ────────────────────────────────────────────────
validate_target_repos_registry(TARGET_REPOS)
validate_metadata_schemas(set(TARGET_REPOS))

# Self-update to the latest published version (skipped with --no-update or when
# BASE_REPO_OWNER is overridden for local development).
ensure_latest_version(
    enabled='--no-update' not in sys.argv and BASE_REPO_OWNER == 'Infineon',
)

try:
    args = Input()
except ValueError as exc:
    print(f'{ICON_ERROR} Error: {exc}', file=sys.stderr)
    sys.exit(1)

print_header(f'{DEEPCRAFT} Pull Request Tool', icon=ICON_PULL_REQUEST)

try:
    target_repo = args.target_repo
    project_path = args.project_path
    branch_name = project_name = args.project_name
    metadata_path = project_path / 'metadata.json'

    # Initial summary
    print_header('Project Summary', icon=ICON_INFO)
    print(f'  Target        : {target_repo.label} ({args.repo_key})')
    print(f'  Repository    : {target_repo.base_repo}')
    print(f'  Project path  : {project_path}')
    print(f'  Project name  : {project_name}')
    print(f'  Branch        : {branch_name}')
    has_existing_metadata = metadata_path.exists()
    meta_status = (
        f'{ICON_SUCCESS} found' if has_existing_metadata
        else f'{ICON_INFO} not found — will be created'
    )
    print(f'  Project layout: {target_repo.project_layout}')
    print(f'  metadata.json : {meta_status}')
    readme_status = (
        f'{ICON_SUCCESS} found' if (project_path / 'README.md').is_file()
        else f'{ICON_WARNING} missing (required)'
    )
    print(f'  README.md     : {readme_status}')
    print()
    if not confirm('Proceed with this project and repository?'):
        print(f'{ICON_ABORT} Aborted by user.')
        sys.exit(0)
    print()

    # Metadata review / collection (after summary so the user can abort first)
    metadata_schema = get_metadata_schema(args.repo_key)
    print_header('Metadata Collection', icon=ICON_INFO)
    if args.override_metadata or not metadata_path.exists():
        metadata = args.collect_metadata()
    else:
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'Could not read existing {metadata_path}: {exc}') from exc
        metadata = validate_loaded_metadata(
            metadata,
            metadata_schema,
            lambda current, field_keys: args.collect_metadata(
                use_cli_args=False,
                previous=current,
                only_fields=field_keys,
            ),
            project_name,
        )

    while metadata:
        metadata = finalize_metadata(metadata, metadata_schema)
        print('\nProject metadata.json overview:')
        print(format_metadata_json(metadata).rstrip('\n'))
        answer = confirm_metadata()
        if answer == 'yes':
            metadata_path.write_text(
                format_metadata_json(metadata),
                encoding='utf-8',
            )
            print(f'{ICON_SUCCESS} Saved metadata.json')
            break
        if answer == 'abort':
            print(f'{ICON_ABORT} Aborted by user.')
            sys.exit(0)
        print(f'{ICON_INFO} Restarting metadata collection... (press Enter to keep previous values)')
        args.metadata = args.collect_metadata(use_cli_args=False, previous=metadata)
        metadata = args.metadata
    validate_project_structure(project_name, project_path, target_repo)
except ValueError as exc:
    print(f'{ICON_ERROR} Error: {exc}', file=sys.stderr)
    sys.exit(1)

print_header('Forking & Syncing Repository', icon=ICON_PROGRESS)
print(f'  {ICON_INFO} Checking git version, authenticating, and preparing fork...')

# Setup git and gh cli
cli = Cli(verbose=args.verbose, base_repo=target_repo.base_repo)
gh_label = Path(cli.gh_executable).name if cli.gh_source == 'bundled' else cli.gh_executable
print(f'  GitHub CLI    : {gh_label} ({cli.gh_source}, {cli.gh_version()})')
if args.verbose:
    print(f'  {ICON_INFO} Verbose mode  : on (all git/gh commands will be printed)')
print()

cli.ensure_git_version()
git = cli.git
gh = cli.gh
# Keep prompts enabled until after auth — login/refresh need the browser flow.
cli.ensure_github_auth(required_scopes=('workflow',))
gh(['config', 'set', 'prompt', 'disabled'])
user = gh(['api', 'user', '--jq', '.login'])
git_name, git_email = resolve_git_identity(user)

# Ensure fork exists and is in-sync with the source repo
cli.progress('Checking fork...')
# Capture JSON (--jq) so raw gh output is not dumped to the terminal.
if not _usable_gh_string(
    gh(['repo', 'view', f'{user}/{target_repo.repo_name}', '--json', 'name', '--jq', '.name'], check=False),
):
    cli.progress('Creating fork...')
    fork(target_repo.base_repo)
elif gh(['repo', 'sync', f'{user}/{target_repo.repo_name}', '--force', '--branch', MAIN_BRANCH], check=False) != 0:
    recreate_fork_with_confirmation(user, target_repo)
else:
    ensure_fork_matches_upstream(user, target_repo)

cli.git_dir = git_dir = project_path.parent / GIT_DIR / target_repo.key / project_name
tool_exit_code = 0
try:  # Always remove git_dir after this block
    while True:
        reset_git_scratch(git_dir)
        try:
            # Initialize local git
            with TemporaryDirectory() as tmpdir:
                cli.cwd = tmpdir
                branch_was_reset = False
                # Clone empty and shallow. --no-single-branch keeps other branch tips fetchable;
                # --filter=blob:none makes it a partial clone so file contents of unrelated
                # projects are never downloaded (only fetched lazily for the sparse path we use),
                # keeping disk/network usage small even when the fork holds many large projects.
                with cli.busy('Cloning your fork (partial clone; large forks take a while)'):
                    git(['clone', '--no-checkout', '--depth', '1', '--no-single-branch', '--filter=blob:none',
                         f'--separate-git-dir={git_dir}',
                         f'{HOST}/{user}/{target_repo.repo_name}.git', tmpdir])
                cli.progress('Configuring local git and sparse checkout...')
                git(['remote', 'add', '-t', MAIN_BRANCH, 'upstream', target_repo.base_repo_url])
                git(['config', 'advice.updateSparsePath', 'false'])
                git(['config', 'core.safecrlf', 'false'])
                git(['config', 'user.name', git_name])
                git(['config', 'user.email', git_email])
                git(['config', 'gc.auto', '0'])
                git(['config', 'maintenance.auto', 'false'])

                # Prevent git from processing tracked files that are outside the project
                git(['sparse-checkout', 'set', '--no-cone', '!/*', f'/{project_name}/'])

                # Switch to the project branch
                branch_ref = f'refs/heads/{branch_name}'
                head_branch = f'{user}:{branch_name}'
                with cli.busy(f'Checking whether branch "{branch_name}" exists on your fork'):
                    # Discard stdout: without this, ls-remote prints the matching ref tip.
                    # Must not use PIPE here — that would return text instead of the exit code.
                    branch_is_new = git(
                        ['ls-remote', '--exit-code', '--quiet', 'origin', branch_ref],
                        check=False,
                        stdout=DEVNULL,
                    ) == 2
                if not branch_is_new:
                    cli.progress('Checking pull-request state for this branch...')
                    pr_state = _usable_gh_string(
                        gh(
                            ['pr', 'view', head_branch, '--json', 'state', '--jq', '.state'],
                            check=False,
                            quiet_stderr=True,
                        ),
                    )
                    if pr_state in ('CLOSED', 'MERGED') and should_reset_branch(pr_state, branch_name):
                        cli.progress(f'Resetting fork branch "{branch_name}" to upstream main...')
                        gh(['api', '-X', 'DELETE',
                            f'repos/{user}/{target_repo.repo_name}/git/refs/heads/{branch_name}'], check=False)
                        branch_is_new = True
                        branch_was_reset = True
                if branch_is_new:
                    with cli.busy(f'Creating local branch "{branch_name}" from main'):
                        git(['switch', '-c', branch_name, MAIN_BRANCH])
                else:
                    with cli.busy(
                        f'Switching to branch "{branch_name}" '
                        '(large projects can take several minutes)',
                    ):
                        git(['switch', branch_name])
                commits_ahead = int(git(['rev-list', '--count', branch_ref, f'^refs/heads/{MAIN_BRANCH}'], stdout=PIPE))
                commit_verb = 'Add' if commits_ahead <= 0 else 'Modify'

            # Print execution summary
            print_header('Creating / Updating Pull Request', icon=ICON_PROGRESS)
            print(f'  GitHub user   : {user}')
            print(f'  Fork          : {user}/{target_repo.repo_name}')
            print(f'  Branch        : {branch_name} ({"new" if branch_is_new else "existing"})')
            print(f'  Mode          : {commit_verb} files')
            print()

            # Push project content to the user's remote (origin)
            cli.cwd = repo_root = project_path.parent
            cli.work_tree = repo_root
            # Handle deletions
            # Use on-disk spellings so a mis-cased Models/ (e.g. models/) is still
            # excluded from the push if validation were ever skipped.
            cli.progress('Preparing ignore rules for Models / local artefacts...')
            ignored_dirs = on_disk_names_matching(project_path, target_repo.git_ignored_dirs)
            ignore_paths = [f':^{project_path.name}/{dir}' for dir in ignored_dirs]
            with cli.busy('Scanning project for local git/Python artefacts to exclude'):
                ignore_paths.extend(build_submission_exclude_pathspecs(project_path))
            with cli.busy('Checking for deleted files'):
                diff_names_deleted = filter_submission_paths(
                    git(
                        [
                            'diff', '--name-only', '--diff-filter=D', '--relative', '--',
                            str(project_path), *ignore_paths,
                        ],
                        stdout=PIPE,
                    ),
                    project_path,
                )
            if diff_names_deleted:
                cli.progress('Staging deletions...')
                with NamedTemporaryFile('w', delete=False) as pathspec:
                    pathspec.write(diff_names_deleted)
                    pathspec.close()
                    git(['rm', f'--pathspec-from-file={pathspec.name}'])
                    os.remove(pathspec.name)
            # Divide push into batches under GitHub size and file-count limits.
            # Prefer diff + ls-files over a full-tree intent-to-add: listing 10k+
            # untracked files that way is much faster and still finds every change.
            with cli.busy('Listing changed files (git diff)'):
                changed_names = filter_submission_paths(
                    git(
                        ['diff', '--name-only', '--relative', '--', str(project_path), *ignore_paths],
                        stdout=PIPE,
                    ),
                    project_path,
                )
            with cli.busy('Listing new untracked files (can be slow on large folders)'):
                untracked_names = filter_submission_paths(
                    git(
                        [
                            'ls-files', '--others', '--exclude-standard', '--',
                            str(project_path), *ignore_paths,
                        ],
                        stdout=PIPE,
                    ),
                    project_path,
                )
            seen: set[str] = set()
            names: list[str] = []
            for name in (*changed_names.splitlines(), *untracked_names.splitlines()):
                name = name.strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
            # GitHub caps the PR file list at 3,000 entries. Commit root-level project
            # files (README.md, metadata.json, *.improj, ...) first so they stay visible
            # to reviewers ahead of large Data/ epochs that follow.
            root_files = [name for name in names if name.count('/') <= 1]
            data_files = [name for name in names if name.count('/') > 1]
            commit_batches: list[tuple[str, list[str]]] = []
            if root_files:
                commit_batches.append(('project files', root_files))
            if data_files:
                cli.progress(
                    f'Splitting {len(data_files)} data file(s) into push-sized chunks '
                    f'(max {GH_PUSH_MAX_FILES} files / ~2 GB each)...',
                )
                data_chunks = list(
                    group_files(
                        repo_root,
                        '\n'.join(data_files),
                        GH_PUSH_MAX_BYTES,
                        max_files=GH_PUSH_MAX_FILES,
                    ),
                )
                if len(data_chunks) == 1:
                    commit_batches.append(('data files', data_chunks[0]))
                else:
                    total = len(data_chunks)
                    for index, chunk in enumerate(data_chunks, start=1):
                        commit_batches.append((f'data chunk {index} of {total}', chunk))
            if commit_batches:
                count = len(commit_batches)
                file_total = sum(len(group) for _, group in commit_batches)
                cli.progress(
                    f'Pushing {file_total} file(s) in {count} commit'
                    f'{"s" if count != 1 else ""}...',
                )
                for index, (label, group) in enumerate(commit_batches, start=1):
                    cli.progress_bar(
                        index - 1,
                        count,
                        f'Commit {index}/{count}: {label} ({len(group)} files)',
                    )
                    stage_paths_with_progress(group, label=label)
                    cli.progress(
                        f'Committing {label} ({len(group)} file'
                        f'{"s" if len(group) != 1 else ""})...',
                    )
                    git(['commit', '--quiet', '--no-verify', '-m', f'{commit_verb} {label}'])
                    cli.progress(f'Pushing {label} to GitHub (please wait)...')
                    push_args = ['push', '-u', 'origin', 'HEAD']
                    if branch_was_reset:
                        push_args.insert(1, '--force-with-lease')
                    git(push_args)
                    cli.progress_bar(
                        index,
                        count,
                        f'Finished {label}',
                        final=True,
                    )
                pushed_changes = True
            elif diff_names_deleted:
                cli.progress('Pushing deletions...')
                git(['commit', '--quiet', '-m', 'Delete files'])
                push_args = ['push', '-u', 'origin', 'HEAD']
                if branch_was_reset:
                    push_args.insert(1, '--force-with-lease')
                git(push_args)
                pushed_changes = True
            else:
                pushed_changes = False
                print('\n' + '=' * 60)
                print(f'  {ICON_INFO} No changes detected — nothing to push.')
                print('=' * 60 + '\n')

            if not ensure_remote_branch_for_pr(
                branch_is_new=branch_is_new,
                pushed_changes=pushed_changes,
                branch_name=branch_name,
            ):
                tool_exit_code = 1
                break

            pr_url = open_or_create_pull_request(
                head_branch, project_name, target_repo,
            )

            if looks_like_url(pr_url or ''):
                print_header('Pull request ready', icon=ICON_SUCCESS)
                print('  The tool opened (or tried to open) the PR in your browser.')
                print('  If the browser did not open, use this URL:')
                print(f'  {pr_url}')
                print()
                print('  Thank you for your submission!')
                print()
                break

            print_header('Finish the pull request in your browser', icon=ICON_WARNING)
            print_manual_pr_next_steps(user, head_branch, target_repo)
            # Do not sys.exit here: that runs cleanup in finally with no message and
            # looks hung after large multi-chunk pushes. Break so cleanup is visible.
            tool_exit_code = 1
            break
        except (CalledProcessError, OSError, Exception) as exc:
            if offer_network_retry('cloning or pushing your project', exc):
                cli.progress('Retrying clone and push...')
                continue
            print_header('Pull Request Failed', icon=ICON_ERROR)
            print(f'  {ICON_ERROR} Something went wrong while creating/updating the PR.')
            print(f'  {ICON_ERROR} Error: {exc}')
            print()
            print(f'  {ICON_WARNING} Some or all of your project may already have been')
            print('  pushed to your fork/branch before this failure. That is normal')
            print('  when the tool pushes in multiple commits.')
            print(f'  {ICON_INFO} Re-running on the same project is safe — it will')
            print('  only push what is still missing and open/reuse the PR.')
            print(f'  {ICON_INFO} Check your fork on GitHub if you want to confirm')
            print('  what is already there.')
            print()
            tool_exit_code = 1
            break
except KeyboardInterrupt:
    print_header('Process Aborted', icon=ICON_ABORT)
    print(f'  {ICON_ABORT} Interrupted by user (Ctrl+C).')
    print(f'  {ICON_INFO} Temporary git state will be cleaned up next...')
    print()
    tool_exit_code = 130
finally:
    cleanup_git_scratch_with_progress(git_dir)

if tool_exit_code:
    sys.exit(tool_exit_code)
