"""Container process boundary for restricted-mode tools and checks.

Only a disposable copy of the project and this worker file are mounted. Never
mount host home, API keys, Docker socket or extra user-granted folders.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path


class IsolationError(RuntimeError):
    pass


def docker_command(workspace: str, name: str) -> list[str]:
    root = Path(workspace).resolve()
    if root == Path(root.anchor) or root == Path.home() or "," in str(root):
        raise IsolationError("Use a dedicated project folder for isolated execution.")
    image = os.environ.get("GRID_SANDBOX_IMAGE", "grid-sandbox:local")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/@:-]*", image):
        raise IsolationError("Invalid sandbox image name")
    docker = shutil.which("docker")
    if not docker:
        raise IsolationError("Restricted mode requires Docker; host execution is disabled.")
    return [
        docker,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "-i",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit=128",
        "--memory=512m",
        "--cpus=1",
        "--ulimit",
        "nofile=256:256",
        "--ulimit",
        "fsize=67108864:67108864",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=128m",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--mount",
        f"type=bind,src={root},dst={root}",
        "--workdir",
        str(root),
        "--mount",
        f"type=bind,src={Path(__file__).with_name('sandbox_worker.py')},dst=/opt/grid-worker.py,readonly",
        image,
        "python",
        "/opt/grid-worker.py",
    ]


def require_isolation():
    docker = shutil.which("docker")
    if not docker:
        raise IsolationError("Restricted mode requires Docker; host execution is disabled.")
    image = os.environ.get("GRID_SANDBOX_IMAGE", "grid-sandbox:local")
    try:
        subprocess.run([docker, "image", "inspect", image], check=True, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as exc:
        raise IsolationError(
            "Sandbox unavailable. Start Docker and build the sandbox image. Host fallback is disabled."
        ) from exc


def run_isolated(payload: dict, workspace: str, *, timeout=120, cancel=None) -> tuple[int, str]:
    import json
    import tempfile
    import time

    name = "grid-" + uuid.uuid4().hex
    args = docker_command(workspace, name)
    with tempfile.TemporaryDirectory(prefix="grid-isolated-") as temp, tempfile.TemporaryFile() as output:
        staged = Path(temp) / "project"
        shutil.copytree(workspace, staged, symlinks=True, ignore=shutil.ignore_patterns(".git", ".grid"))
        before = manifest(staged)
        mount = args.index("--mount") + 1
        args[mount] = f"type=bind,src={staged},dst={Path(workspace).resolve()}"
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT)
        try:
            process.stdin.write(json.dumps(payload).encode())
            process.stdin.close()
            start = time.monotonic()
            while process.poll() is None:
                if os.fstat(output.fileno()).st_size > 8_000_000:
                    raise IsolationError("Isolated output limit exceeded")
                if (cancel and cancel.is_set()) or time.monotonic() - start >= timeout:
                    raise IsolationError("Isolated execution cancelled or timed out")
                time.sleep(0.05)
            output.seek(0, os.SEEK_END)
            output.seek(max(0, output.tell() - 2_000_000))
            text = output.read().decode(errors="replace")
            sync_project(staged, Path(workspace).resolve(), before)
            return process.returncode, text
        finally:
            # Kill descendants in the container too, even if the Docker client
            # exits or is interrupted before it can remove the container.
            try:
                subprocess.run([args[0], "rm", "-f", name], capture_output=True, timeout=10, check=False)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()


def manifest(root):
    import hashlib

    rows = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            p = Path(folder) / name
            rel = str(p.relative_to(root))
            if p.is_symlink():
                rows[rel] = ("link", os.readlink(p))
            elif p.is_file():
                rows[rel] = ("file", hashlib.sha256(p.read_bytes()).hexdigest())
    return rows


def sync_project(staged, root, before):
    """Import regular-file changes with no-follow directory descriptors.

    Never follow a project symlink into the host. Atomic replacement also breaks
    hardlinks instead of modifying their targets. Reject changed links as a batch.
    """
    import stat

    after = manifest(staged)
    changed = [name for name in before.keys() | after.keys() if before.get(name) != after.get(name)]
    if any((after.get(name) or ("",))[0] == "link" for name in changed):
        raise IsolationError("Sandbox symlink changes cannot be imported.")
    if any(any(part in (".git", ".grid", "..") for part in Path(name).parts) for name in changed):
        raise IsolationError("Protected project path")
    # Check external edits before importing any changes.
    current = manifest(root)
    if any(current.get(name) != before.get(name) for name in changed):
        raise IsolationError("Project changed outside this task; sandbox changes were not imported.")
    for name in sorted(changed):
        parts = Path(name).parts
        if any(part in (".git", ".grid", "..") for part in parts):
            raise IsolationError("Protected project path")
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            if name not in after:
                os.unlink(parts[-1], dir_fd=fd)
            else:
                temp = ".grid-import-" + uuid.uuid4().hex
                handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                try:
                    with os.fdopen(handle, "wb") as out:
                        out.write((staged / name).read_bytes())
                    mode = stat.S_IMODE((staged / name).stat().st_mode) & 0o777
                    os.chmod(temp, mode, dir_fd=fd)
                    os.replace(temp, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
                finally:
                    try:
                        os.unlink(temp, dir_fd=fd)
                    except FileNotFoundError:
                        pass
        finally:
            os.close(fd)
