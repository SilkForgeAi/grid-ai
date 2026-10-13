import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/release" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_public_staging_has_only_curated_documents(tmp_path):
    staging = tmp_path / "public"
    module("prepare_public_repo").prepare(staging)
    assert {p.name for p in staging.iterdir()} == {"README.md", "SUPPORT.md", "LICENSE"}
    with pytest.raises(ValueError, match="empty"):
        module("prepare_public_repo").prepare(staging)
    with pytest.raises(ValueError, match="outside"):
        module("prepare_public_repo").prepare(ROOT / "dist/public")


def test_app_only_check_rejects_python_inside_bundled_wheel(tmp_path):
    wheel = io.BytesIO()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("grid/safety.py", "secret implementation")
    artifact = tmp_path / "Grid-macOS-arm64.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("Grid.app/Contents/Resources/engine/grid_ai-0.2.0-py3-none-any.whl", wheel.getvalue())
    with pytest.raises(ValueError, match="Grid code"):
        module("check_app_only").check(artifact)


@pytest.mark.parametrize("name", ["../escape", ".git/config", "engine/.env", "signing.p12", "grid/session.pyc"])
def test_app_only_check_rejects_private_paths(tmp_path, name):
    artifact = tmp_path / "Grid.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(name, "private")
    with pytest.raises(ValueError):
        module("check_app_only").check(artifact)


def test_app_only_check_allows_binaries_and_dependency_notices(tmp_path):
    artifact = tmp_path / "Grid.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("Grid.app/Contents/MacOS/Grid", b"binary")
        archive.writestr("Grid.app/Contents/Resources/notices/python/func_timeout/LICENSE", "third-party notice")
    module("check_app_only").check(artifact)


@pytest.mark.parametrize('name', [
    '.git/config', '.env', 'src/grid/.env.local', 'desktop/engine/grid.whl',
    'desktop/node_modules/private.js', 'src/grid/models.json', 'tests/secret.pem',
    'src/grid/local.gguf', 'src/grid/foo 2.py', 'docs/release/PUBLICATION_PRIVACY_REVIEW.md',
])
def test_source_snapshot_excludes_private_files(name):
    assert not module('prepare_source_repo').allowed(name)


@pytest.mark.parametrize('name', [
    'src/grid/models.py', 'tests/test_models.py', 'desktop/main.js',
    '.env.example', 'LICENSE', '.github/workflows/ci.yml',
    'src/grid/plugins_builtin/teach/.plugin/plugin.json',
])
def test_source_snapshot_includes_learning_and_build_files(name):
    assert module('prepare_source_repo').allowed(name)


def test_source_snapshot_copies_current_files_without_history(tmp_path):
    import subprocess

    source = tmp_path / 'private'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    (source / 'src/grid').mkdir(parents=True)
    (source / 'src/grid/app.py').write_text('print("learn")')
    (source / 'src/grid/models.json').write_text('{"personal":true}')
    (source / '.env').write_text('EXAMPLE_KEY=personal')
    destination = tmp_path / 'public'
    assert module('prepare_source_repo').prepare(destination, root=source) == 1
    assert (destination / 'src/grid/app.py').read_text() == 'print("learn")'
    assert not (destination / '.git').exists()
    assert not (destination / '.env').exists()
    assert not (destination / 'src/grid/models.json').exists()


def test_source_snapshot_rejects_symlinks(tmp_path):
    import subprocess

    source = tmp_path / 'private'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    (source / 'src').mkdir()
    outside = tmp_path / 'personal'
    outside.write_text('private')
    (source / 'src/leak.py').symlink_to(outside)
    with pytest.raises(ValueError, match='link'):
        module('prepare_source_repo').prepare(tmp_path / 'public', root=source)


def test_mit_app_archive_allows_grid_source_but_still_rejects_credentials(tmp_path):
    artifact = tmp_path / 'Grid.zip'
    with zipfile.ZipFile(artifact, 'w') as archive:
        archive.writestr('grid/app.py', 'print("learn")')
    module('check_app_only').check(artifact, allow_source=True)
    with zipfile.ZipFile(artifact, 'a') as archive:
        archive.writestr('grid/signing.pem', 'private')
    with pytest.raises(ValueError, match='Credential'):
        module('check_app_only').check(artifact, allow_source=True)
