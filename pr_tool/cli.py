import itertools
import json
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, run, PIPE

from constants import (
    ICON_ERROR,
    ICON_INFO,
    ICON_PROGRESS,
    ICON_WARNING,
    MINIMUM_GIT_VERSION,
    MINIMUM_UPDATABLE_GIT_VERSION,
)

# Define convenient functions to operate on the git tree
CliResult = CompletedProcess | str | int

TOOL_DIR = Path(__file__).resolve().parent

# Substrings that usually mean a transient GitHub connectivity problem.
_NETWORK_ERROR_MARKERS = (
    'failed to connect',
    "couldn't connect to server",
    'could not resolve host',
    'name or service not known',
    'timed out',
    'timeout',
    'connection reset',
    'connection refused',
    'network is unreachable',
    'unable to access',
    'promisor remote',
    'the remote end hung up',
    'error: rpc failed',
    'ssl_error',
    'ssl error',
    'tls',
    'proxy',
)


def is_network_error(message: str) -> bool:
    """Return True if *message* looks like a GitHub / network connectivity failure."""
    text = message.casefold()
    return any(marker in text for marker in _NETWORK_ERROR_MARKERS)


def called_process_error_text(exc: CalledProcessError) -> str:
    """Combine stderr/stdout from a failed subprocess for classification and display."""
    parts: list[str] = []
    for raw in (exc.stderr, exc.stdout):
        if not raw:
            continue
        if isinstance(raw, bytes):
            parts.append(raw.decode(errors='replace').strip())
        else:
            parts.append(str(raw).strip())
    if parts:
        return '\n'.join(part for part in parts if part)
    return str(exc)


def print_network_failure(action: str, detail: str) -> None:
    """Explain a GitHub connectivity failure in plain language."""
    print()
    print('=' * 60)
    print(f'  {ICON_ERROR} Could not reach GitHub while: {action}')
    print('=' * 60)
    print(f'  {ICON_INFO} This is a network problem (firewall, VPN, proxy,')
    print('  DNS, or a temporary outage) — not an issue with your project.')
    print(f'  {ICON_INFO} Check https://github.com in a browser, then retry.')
    if detail.strip():
        first_line = next(
            (line.strip() for line in detail.splitlines() if line.strip()),
            detail.strip(),
        )
        print(f'  {ICON_WARNING} Detail: {first_line[:200]}')
    print('=' * 60)
    print()


def _resolve_gh_executable() -> tuple[str, str]:
    """Return ``(executable path, source label)`` for GitHub CLI.

    Prefers ``gh.exe`` / ``gh`` shipped next to this module, then ``gh`` on ``PATH``.
    """
    for name in ('gh.exe', 'gh'):
        bundled = TOOL_DIR / name
        if bundled.is_file():
            return str(bundled), 'bundled'
    on_path = shutil.which('gh')
    if on_path:
        return on_path, 'PATH'
    expected = TOOL_DIR / 'gh.exe'
    print(
        f'{ICON_ERROR} Error: GitHub CLI (gh) not found.\n'
        f'  Expected bundled executable at: {expected}\n'
        '  Quick fix:\n'
        '  1) Install GitHub CLI: https://cli.github.com/\n'
        '  2) Add the install folder (not gh.exe) to PATH\n'
        '  3) Restart your terminal/shell and run again',
        file=sys.stderr,
    )
    sys.exit(1)


class Cli:
    def __init__(self, *, verbose: bool = False, base_repo: str):
        self.cwd = None
        self.git_dir = None
        self.work_tree = None
        self.verbose = verbose
        self.base_repo = base_repo
        self.gh_executable, self.gh_source = _resolve_gh_executable()

    def _finish_progress_line(self) -> None:
        """End an in-place ``\\r`` progress line so the next print starts cleanly."""
        width = getattr(self, '_progress_width', 0)
        if width:
            print(flush=True)
            self._progress_width = 0

    def progress(self, message: str) -> None:
        """Print a short status line (always shown in quiet mode)."""
        self._finish_progress_line()
        if not self.verbose:
            print(f'  {ICON_PROGRESS} {message}')

    def progress_bar(
        self,
        done: int,
        total: int,
        message: str,
        *,
        final: bool = False,
    ) -> None:
        """Show ``[####----] done/total (pct%) message`` (quiet mode only).

        On a TTY, updates in place with ``\\r`` until *final* or *done* >= *total*.
        """
        if self.verbose:
            return
        total = max(int(total), 0)
        done = max(0, min(int(done), total if total else 0))
        if total <= 0:
            self.progress(message)
            return
        pct = int(100 * done / total)
        filled = int(24 * done / total)
        bar = '#' * filled + '-' * (24 - filled)
        line = f'  {ICON_PROGRESS} [{bar}] {done}/{total} ({pct}%)  {message}'
        use_cr = sys.stdout.isatty() and not final and done < total
        if use_cr:
            width = max(getattr(self, '_progress_width', 0), len(line))
            self._progress_width = width
            print('\r' + line.ljust(width), end='', flush=True)
            return
        self._finish_progress_line()
        print(line, flush=True)
        self._progress_width = 0

    @contextmanager
    def busy(self, message: str):
        """Animate a status line while a long operation runs (quiet mode + TTY).

        Use around clone/switch/scan steps that can take minutes with no output.
        """
        if self.verbose or not sys.stdout.isatty():
            self.progress(f'{message}...')
            yield
            return

        stop = threading.Event()
        frames = itertools.cycle('|/-\\')

        def _spin() -> None:
            # First paint immediately so the user sees activity before the wait.
            frame = next(frames)
            line = f'  {ICON_PROGRESS} {message}...  {frame}'
            width = max(getattr(self, '_progress_width', 0), len(line))
            self._progress_width = width
            print('\r' + line.ljust(width), end='', flush=True)
            while not stop.wait(0.4):
                frame = next(frames)
                line = f'  {ICON_PROGRESS} {message}...  {frame}'
                width = max(getattr(self, '_progress_width', 0), len(line))
                self._progress_width = width
                print('\r' + line.ljust(width), end='', flush=True)

        thread = threading.Thread(target=_spin, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=1.0)
            elapsed = max(0, int(time.monotonic() - started))
            self._finish_progress_line()
            if elapsed >= 2:
                print(f'  {ICON_PROGRESS} {message}... done ({elapsed}s)', flush=True)
            else:
                print(f'  {ICON_PROGRESS} {message}... done', flush=True)

    def gh_version(self) -> str:
        """Return the ``gh --version`` string (first line), or ``unknown``."""
        try:
            result = run(
                [self.gh_executable, '--version'],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip().splitlines()[0]
        except OSError:
            pass
        return 'unknown version'

    def run(self, args: list, *popenargs, cwd=None, check=True, stdout=None, stderr=None,
            quiet_stderr: bool = False, **kwargs) -> CliResult:
        cmd = ' '.join(args)
        if self.verbose:
            print(cmd)
        capture_stderr = stderr is None
        if capture_stderr:
            stderr = PIPE
        try:
            result = run(
                args, *popenargs, cwd=cwd or self.cwd, check=False,
                stdout=stdout, stderr=stderr, **kwargs,
            )
        except OSError as exc:
            print(f'{ICON_ERROR} Command failed: {cmd}', file=sys.stderr)
            raise CalledProcessError(1, args, None, str(exc).encode()) from exc
        stderr_text = ''
        if result.stderr:
            stderr_text = (
                result.stderr.decode(errors='replace')
                if isinstance(result.stderr, bytes)
                else str(result.stderr)
            )
            show_stderr = capture_stderr and stderr_text and (
                self.verbose or (result.returncode != 0 and not quiet_stderr)
            )
            if show_stderr:
                sys.stderr.write(
                    stderr_text if stderr_text.endswith('\n') else f'{stderr_text}\n',
                )
        if check and result.returncode != 0:
            print(f'{ICON_ERROR} Command failed: {cmd}', file=sys.stderr)
            raise CalledProcessError(result.returncode, args, result.stdout, result.stderr)
        if stdout == PIPE:
            output = (result.stdout or b'').decode().strip()
            if self.verbose:
                shown = output[:512] if output else f'(exit {result.returncode})'
                print('-> ' + shown)
            # Never coerce a failed/empty --jq result into the exit-code string
            # (e.g. "1"); callers treat empty as missing.
            return output
        if not check and self.verbose:
            print(f'-> {result.returncode}')
        return result.returncode if not check else result

    def git(self, args: list, *popenargs, **kwargs) -> CliResult:
        base = ['git', f'--git-dir={self.git_dir}']
        # --work-tree on the command line overrides any stale ``core.worktree`` left
        # behind by ``clone --separate-git-dir`` (which points at the deleted tmpdir).
        if self.work_tree is not None:
            base.append(f'--work-tree={self.work_tree}')
        return self.run(base + args, *popenargs, **kwargs)

    def gh(self, args: list, *popenargs, **kwargs) -> CliResult:
        if args[0] == 'pr':
            # All PR commands interact with Infineon's repo (the fork's base repo)
            args.extend(['--repo', self.base_repo])
        if '--jq' in args:
            # Commands with JQ are assumed to have a query that outputs a string value
            kwargs['stdout'] = PIPE
        return self.run([self.gh_executable] + args, *popenargs, **kwargs)

    def _parse_github_scopes(self, scopes: object) -> set[str]:
        if isinstance(scopes, str):
            return {part.strip() for part in scopes.split(',') if part.strip()}
        if isinstance(scopes, list):
            return {str(scope).strip() for scope in scopes if str(scope).strip()}
        return set()

    def _active_github_host(self) -> dict | None:
        """Return the active github.com auth host entry, or ``None`` if not logged in."""
        try:
            output = self.run(
                [self.gh_executable, 'auth', 'status', '--hostname', 'github.com', '--json', 'hosts'],
                stdout=PIPE,
                check=False,
            )
        except OSError:
            return None
        if not isinstance(output, str) or not output.strip():
            return None
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        hosts = (payload.get('hosts') or {}).get('github.com')
        if not hosts:
            return None
        if not isinstance(hosts, list):
            hosts = [hosts]
        return next((host for host in hosts if host.get('active')), hosts[0] if hosts else None)

    def ensure_github_auth(self, *, required_scopes: tuple[str, ...] = ('workflow',)) -> None:
        """Ensure GitHub CLI is logged in with the scopes this tool needs."""
        host = self._active_github_host()
        if host is None or host.get('state') != 'success':
            login = host.get('login') if host else None
            detail = host.get('error') if host else None
            print(
                f'{ICON_INFO} GitHub CLI is not authenticated for github.com'
                + (f' (account: {login})' if login else '')
                + '.',
            )
            if detail:
                print(f'  {ICON_INFO} {detail}')
            print(
                f'  {ICON_INFO} Opening browser login '
                f'(this tool uses: {self.gh_executable})...',
            )
            self.gh(['auth', 'login', '--hostname', 'github.com', '--web',
                     '--git-protocol', 'https', '--scopes', ','.join(required_scopes)])
            host = self._active_github_host()
            if host is None or host.get('state') != 'success':
                raise Exception(
                    f'{ICON_ERROR} GitHub login did not complete. '
                    f'Run: "{self.gh_executable}" auth login -h github.com',
                )
            return

        granted = self._parse_github_scopes(host.get('scopes'))
        missing = [scope for scope in required_scopes if scope not in granted]
        if missing:
            self.progress(
                f'Adding missing GitHub token scope(s): {", ".join(missing)}',
            )
            self.gh(['auth', 'refresh', '--hostname', 'github.com',
                     '-s', ','.join(missing)])
            host = self._active_github_host()
            granted = self._parse_github_scopes(host.get('scopes') if host else None)
            still_missing = [scope for scope in required_scopes if scope not in granted]
            if still_missing:
                raise Exception(
                    f'{ICON_ERROR} GitHub token is still missing scope(s): '
                    f'{", ".join(still_missing)}. '
                    f'Run: "{self.gh_executable}" auth refresh -h github.com '
                    f'-s {",".join(still_missing)}',
                )

    def ensure_git_version(self) -> None:
        """Ensure that git version is enough."""
        version = self.git(['version'], stdout=PIPE).rpartition(' ')[2]
        version_msg = f'git version {MINIMUM_GIT_VERSION} or newer is required.'
        if _git_version_less(version, MINIMUM_GIT_VERSION):
            # The message clarifies why update-git-for-windows is called
            print(f'{ICON_ERROR} {version_msg}')
        if _git_version_less(version, MINIMUM_UPDATABLE_GIT_VERSION) or (
                _git_version_less(version, MINIMUM_GIT_VERSION)
                and self.git(['update-git-for-windows'], check=False) == 1):
            raise Exception(f'{ICON_ERROR} {version_msg}')


def _parse_git_version(version: str) -> tuple[int, ...]:
    """Parse a git version string into a comparable numeric tuple.

    Examples: ``2.43.0`` → ``(2, 43, 0)``; ``2.43.0.windows.1`` → ``(2, 43, 0)``.
    """
    parts: list[int] = []
    for chunk in version.strip().split('.'):
        digits = []
        for char in chunk:
            if char.isdigit():
                digits.append(char)
            else:
                break
        if not digits:
            break
        parts.append(int(''.join(digits)))
    return tuple(parts) if parts else (0,)


def _git_version_less(left: str, right: str) -> bool:
    """Return True if *left* is a lower git version than *right*."""
    return _parse_git_version(left) < _parse_git_version(right)
