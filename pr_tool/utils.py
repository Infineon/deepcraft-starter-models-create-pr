import os
import stat
from collections.abc import Iterator
from pathlib import Path


def group_files(
    root: str | Path,
    files: str,
    max_size: int,
    max_files: int | None = None,
) -> Iterator[list[str]]:
    """Group paths so each batch stays under *max_size* bytes and *max_files* entries.

    Yields lists of absolute paths (resolved under *root*). A single file larger
    than *max_size* raises ``ValueError``. When *max_files* is ``None``, only the
    size limit applies (legacy behaviour).
    """
    group: list[str] = []
    group_size = 0
    for file in files.splitlines():
        if not file:
            continue
        file_path = Path(root, file)
        file_size = file_path.stat().st_size if file_path.exists() else 0
        if file_size > max_size:
            raise ValueError(
                f'File {file_path} of size {file_size} bytes exceeds the maximum '
                f'allowed size of {max_size} bytes.',
            )
        would_exceed_size = bool(group) and group_size + file_size > max_size
        would_exceed_count = (
            max_files is not None and bool(group) and len(group) >= max_files
        )
        if would_exceed_size or would_exceed_count:
            yield group
            group = []
            group_size = 0
        group.append(str(file_path))
        group_size += file_size
    if group:
        yield group


def handle_readonly(func, path, exc):
    os.chmod(path, stat.S_IWRITE)
    os.unlink(path)
