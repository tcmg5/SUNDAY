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


def test_rejects_protected_names_even_inside_root(sandbox):
    ssh = sandbox / ".ssh"
    ssh.mkdir()
    with pytest.raises(UnsafePathError) as exc:
        resolve_under(ssh / "id_rsa", [sandbox])
    assert "protected" in str(exc.value)


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
