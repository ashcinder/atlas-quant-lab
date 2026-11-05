"""Reclaim only marked segments under a locked, private task directory (POSIX)."""
from contextlib import contextmanager
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

LOGGER = logging.getLogger(__name__)
MARKER = '.owner.json'
SEGMENT_NAME = re.compile(r'^\.proof-segments-[0-9a-f]{32}$')
SCHEMA = 'atlas.proof.segments.v1'


@contextmanager
def _task_lock(output):
    root = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = None
    try:
        info = os.fstat(root)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('分段任务目录必须私有且属于当前用户')
        lock = os.open('.proof-segments.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                       0o600, dir_fd=root)
        lock_info = os.fstat(lock)
        if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid()
                or lock_info.st_nlink != 1 or lock_info.st_mode & 0o077):
            raise PermissionError('分段任务锁不安全')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
            return
        yield root, lock, {'schema': SCHEMA, 'root_device': info.st_dev,
                           'root_inode': info.st_ino, 'uid': info.st_uid}
    finally:
        # Do not LOCK_UN: a surviving child inherits this open-file-description.
        if lock is not None:
            os.close(lock)
        os.close(root)


def _cleanup(root, owner):
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError('当前平台不支持安全分段目录清理')
    for name in os.listdir(root):
        if not SEGMENT_NAME.fullmatch(name):
            continue
        child = None
        try:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            info = os.fstat(child)
            if info.st_uid != owner['uid'] or info.st_mode & 0o077:
                continue
            marker = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=child)
            with os.fdopen(marker, 'rb') as handle:
                marked = json.loads(handle.read(2048))
            if marked != {**owner, 'name': name}:
                continue
            current = os.stat(name, dir_fd=root, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                continue
            shutil.rmtree(name, dir_fd=root)
        except (OSError, ValueError):
            LOGGER.warning('跳过无法确认归属或无法清理的分段目录')
        finally:
            if child is not None:
                os.close(child)


def cleanup_segments(output):
    """False means an active holder; never clean or rename that task."""
    with _task_lock(output) as lease:
        if lease is None:
            LOGGER.info('分段任务仍持有锁，跳过回收')
            return False
        root, _, owner = lease
        _cleanup(root, owner)
        return True


@contextmanager
def segment_workspace(output):
    output = Path(os.path.abspath(output))
    with _task_lock(output) as lease:
        if lease is None:
            raise RuntimeError('同一任务已有证明进程，不能重复生成')
        root, lock, owner = lease
        _cleanup(root, owner)
        name = '.proof-segments-' + uuid.uuid4().hex
        os.mkdir(name, 0o700, dir_fd=root)
        try:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                marker = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=child)
                with os.fdopen(marker, 'w') as handle:
                    json.dump({**owner, 'name': name}, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                os.close(child)
        except BaseException:
            # No execution data exists yet; remove our just-created directory
            # even when the ownership marker could not be fully written.
            shutil.rmtree(name, dir_fd=root)
            raise
        try:
            yield output / name, lock
        finally:
            _cleanup(root, owner)
