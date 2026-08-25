"""The path guard is the only thing between 'organize my downloads' and disaster."""
import pytest

from jarvis.core.safety import UnsafePathError, is_safe, resolve_under, unique_destination


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    return root


def test_allows_paths_inside_root(sandbox):
    assert resolve_under(sandbox / "a.txt", [sandbox]) == (sandbox / "a.txt").resolve()


def test_rejects_paths_outside_root(sandbox, tmp_path):
    outside = tmp_path / "secrets.txt"
    outside.write_text("nope")
    with pytest.raises(UnsafePathError):
        resolve_under(outside, [sandbox])


def test_rejects_traversal_escape(sandbox):
    # The classic. Resolution happens before the check, so this must fail.
    with pytest.raises(UnsafePathError):
        resolve_under(sandbox / ".." / ".." / "etc" / "passwd", [sandbox])


def test_rejects_protected_names_inside_root(sandbox):
    """A sensitive subtree below an authorised root is still refused."""
    ssh = sandbox / ".ssh"
    ssh.mkdir()
    with pytest.raises(UnsafePathError) as exc:
        resolve_under(ssh / "id_rsa", [sandbox])
    assert "protected" in str(exc.value)


@pytest.mark.parametrize("protected", [".ssh", ".aws", ".git", "node_modules", ".netrc"])
def test_each_protected_name_is_refused_below_the_root(sandbox, protected):
    with pytest.raises(UnsafePathError):
        resolve_under(sandbox / protected / "secret", [sandbox])


def test_protected_names_above_the_root_are_ignored(tmp_path):
    r"""Regression: the guard used to scan the whole absolute path, so any root
    nested under a name like 'AppData' was unusable. That is every temp
    directory on Windows (C:\Users\x\AppData\Local\Temp\...), and the user
    already authorised those ancestors by configuring the root."""
    root = tmp_path / "AppData" / "Local" / "Temp" / "Downloads"
    root.mkdir(parents=True)
    target = root / "invoice.pdf"
    target.write_text("x")

    assert resolve_under(target, [root]) == target.resolve()
    # ...and the protection still applies below that root.
    with pytest.raises(UnsafePathError):
        resolve_under(root / ".ssh" / "id_rsa", [root])


def test_windows_style_ancestors_do_not_block_a_root(tmp_path):
    for ancestor in ("Library", "System", "Windows", "Program Files", ".config"):
        root = tmp_path / ancestor / "Docs"
        root.mkdir(parents=True)
        (root / "note.txt").write_text("x")
        assert resolve_under(root / "note.txt", [root]), f"{ancestor} blocked its own root"


def test_traversal_into_a_protected_sibling_still_fails(tmp_path):
    """Escaping the root remains refused regardless of the relative-parts change."""
    root = tmp_path / "AppData" / "Local" / "Downloads"
    root.mkdir(parents=True)
    secrets = tmp_path / "AppData" / "Roaming" / "creds"
    secrets.mkdir(parents=True)
    with pytest.raises(UnsafePathError):
        resolve_under(root / ".." / ".." / "Roaming" / "creds", [root])


def test_rejects_when_no_roots_configured(sandbox):
    with pytest.raises(UnsafePathError):
        resolve_under(sandbox / "a.txt", [])


def test_must_exist_flag(sandbox):
    with pytest.raises(UnsafePathError):
        resolve_under(sandbox / "ghost.txt", [sandbox], must_exist=True)
    # ...but non-existent destinations are fine when we're about to create them.
    assert resolve_under(sandbox / "ghost.txt", [sandbox])


def test_sibling_prefix_is_not_inside_root(tmp_path):
    """'/data/Downloads-old' must not pass a check against '/data/Downloads'."""
    root = tmp_path / "Downloads"
    root.mkdir()
    sibling = tmp_path / "Downloads-old"
    sibling.mkdir()
    assert not is_safe(sibling / "x.txt", [root])


def test_unique_destination_avoids_clobbering(sandbox):
    existing = sandbox / "a.txt"
    assert unique_destination(existing) == sandbox / "a (2).txt"
    (sandbox / "a (2).txt").write_text("x")
    assert unique_destination(existing) == sandbox / "a (3).txt"


def test_unique_destination_passes_through_free_names(sandbox):
    free = sandbox / "brand-new.txt"
    assert unique_destination(free) == free
