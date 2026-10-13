# Windows release work remaining

Windows is a requested target, not a supported build today. Packaging the current
Electron shell as an EXE alone does not make its engine Windows-compatible.

Before a public Windows download:

1. Replace POSIX-only `fcntl` locks in execution, schedules and checkpoints with
   tested cross-process Windows locking, preserving nonblocking and reentrant
   semantics. Test concurrent chat/editor/schedule writes on NTFS.
2. Implement and exercise a ConPTY terminal or a supported Linux engine bridge.
   The current PTY and SDK terminal use POSIX facilities; no silent host fallback
   is acceptable in restricted mode.
3. Port engine discovery/bootstrap to `uv.exe`, Windows PATH separators and
   `Scripts/python.exe`/`Scripts/grid.exe`. Exercise fresh install, upgrade,
   spaces/non-ASCII paths, encrypted keys, engine shutdown and uninstall.
4. Preserve verification cancellation for entire process trees using Windows
   process/job primitives. Test timeouts and child processes on Windows.
5. Port Docker project mounts, UID assumptions and safe result import. Windows
   lacks the current no-follow directory-descriptor API. Do not weaken symlink,
   junction, hardlink, stale-write or protected-path checks to make it run.
6. Package and test the Grid engine on Windows. Inspect the installer and installed
   engine to exclude personal build paths, credentials, saved profiles, local model
   weights and private history. Keep required third-party source/notices.
7. Package an installer, sign the shipped executables and installer with a valid
   publisher certificate, validate signatures, and test on a clean Windows 11 VM.
   A valid signature does not guarantee absence of SmartScreen reputation prompts.
8. Record the exact artifact SHA-256 and native install/safety/signature test
   evidence in `artifacts-review.json`, then clear the distribution review.

All eight steps are required before advertising Windows as available. Current
macOS tests provide no evidence that a Windows build works.

Microsoft signing documentation:
https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
