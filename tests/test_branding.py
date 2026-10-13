"""Keep Grid-owned presentation and examples free of unrelated product names."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_NAMES = re.compile(r'clau[d]e|code[x]|chatg[p]t', re.IGNORECASE)


def test_grid_owned_source_examples_and_ui_use_neutral_names():
    candidates = [ROOT / name for name in (
        'README.md', 'RUNBOOK.md', 'CONTRIBUTING.md', '.env.example', 'pyproject.toml',
    )]
    for folder in ('src', 'tests', 'scripts', 'release-public'):
        candidates.extend((ROOT / folder).rglob('*'))
    failures = []
    for path in candidates:
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        if path.suffix not in {'.py', '.js', '.html', '.css', '.md', '.json', '.toml', '.example'}:
            continue
        if PRODUCT_NAMES.search(str(path.relative_to(ROOT))) or PRODUCT_NAMES.search(path.read_text()):
            failures.append(str(path.relative_to(ROOT)))
    assert failures == []


def test_plugin_catalog_uses_the_sdk_neutral_manifest_layout():
    from grid.plugins import builtin_catalog

    plugins = builtin_catalog()
    assert len(plugins) >= 5
    for plugin in plugins:
        assert (Path(plugin.path) / '.plugin/plugin.json').is_file()
