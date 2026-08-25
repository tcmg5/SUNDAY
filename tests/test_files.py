"""Organizer: planning, applying, and getting it all back again."""
import time
from pathlib import Path

import pytest

from jarvis.brain.tools import files


@pytest.fixture
def cfg(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    return {
        "files": {
            "safe_roots": [str(downloads)],
            "confirm_threshold": 25,
            "use_trash": True,
            "journal_path": str(tmp_path / "journal.jsonl"),
        },
        "_downloads": downloads,
    }


def populate(directory: Path, names):
    for name in names:
        (directory / name).write_text("x" * 10)


def test_categorize_by_extension():
    assert files.categorize(Path("holiday.JPG")) == "Images"
    assert files.categorize(Path("report.pdf")) == "Documents"
    assert files.categorize(Path("main.py")) == "Code"
    assert files.categorize(Path("mystery.xyz")) == "Other"


def test_build_plan_groups_by_type(cfg):
    downloads = cfg["_downloads"]
    populate(downloads, ["a.jpg", "b.png", "c.pdf", "d.py"])
    plan = files.build_plan(downloads, "by_type")
    destinations = {Path(m["dst"]).parent.name for m in plan}
    assert destinations == {"Images", "Documents", "Code"}
    assert len(plan) == 4


def test_build_plan_skips_already_filed_files(cfg):
    downloads = cfg["_downloads"]
    images = downloads / "Images"
    images.mkdir()
    (images / "already.jpg").write_text("x")
    populate(downloads, ["loose.jpg"])
    plan = files.build_plan(downloads, "by_type")
    assert len(plan) == 1
    assert Path(plan[0]["src"]).name == "loose.jpg"


def test_build_plan_ignores_hidden_files_by_default(cfg):
    downloads = cfg["_downloads"]
    populate(downloads, [".DS_Store", "visible.pdf"])
    plan = files.build_plan(downloads, "by_type")
    assert len(plan) == 1


def test_build_plan_is_pure(cfg):
    """Planning must never touch the disk - that's the whole point of dry_run."""
    downloads = cfg["_downloads"]
    populate(downloads, ["a.jpg", "b.pdf"])
    before = sorted(p.name for p in downloads.iterdir())
    files.build_plan(downloads, "by_type")
    assert sorted(p.name for p in downloads.iterdir()) == before


def test_older_than_days_filter(cfg):
    downloads = cfg["_downloads"]
    populate(downloads, ["fresh.pdf", "ancient.pdf"])
    old = downloads / "ancient.pdf"
    stale = time.time() - 40 * 86400
    import os

    os.utime(old, (stale, stale))
    plan = files.build_plan(downloads, "by_type", older_than_days=30)
    assert len(plan) == 1
    assert Path(plan[0]["src"]).name == "ancient.pdf"


def test_dry_run_moves_nothing(cfg):
    downloads = cfg["_downloads"]
    populate(downloads, ["a.jpg", "b.pdf"])
    result = files.organize_files(cfg, directory=str(downloads), dry_run=True)
    assert "PLAN" in result
    assert (downloads / "a.jpg").exists()
    assert not (downloads / "Images").exists()


def test_apply_then_undo_round_trip(cfg):
    downloads = cfg["_downloads"]
    names = ["a.jpg", "b.png", "c.pdf", "d.py"]
    populate(downloads, names)

    files.organize_files(cfg, directory=str(downloads), dry_run=False)
    assert (downloads / "Images" / "a.jpg").exists()
    assert (downloads / "Documents" / "c.pdf").exists()
    assert not (downloads / "a.jpg").exists()

    files.undo_last_organize(cfg)
    for name in names:
        assert (downloads / name).exists(), f"{name} was not restored"
    # Emptied folders should be cleaned up too.
    assert not (downloads / "Images").exists()


def test_large_batch_requires_confirmation(cfg):
    downloads = cfg["_downloads"]
    populate(downloads, [f"file{i}.pdf" for i in range(30)])
    result = files.organize_files(cfg, directory=str(downloads), dry_run=False)
    assert "confirmation threshold" in result
    assert (downloads / "file0.pdf").exists()  # nothing moved

    result = files.organize_files(
        cfg, directory=str(downloads), dry_run=False, confirmed=True
    )
    assert (downloads / "Documents" / "file0.pdf").exists()


def test_refuses_directory_outside_safe_roots(cfg, tmp_path):
    from jarvis.core.safety import UnsafePathError

    other = tmp_path / "Elsewhere"
    other.mkdir()
    (other / "a.jpg").write_text("x")
    with pytest.raises(UnsafePathError):
        files.organize_files(cfg, directory=str(other), dry_run=True)


def test_collision_gets_suffixed_not_overwritten(cfg):
    downloads = cfg["_downloads"]
    images = downloads / "Images"
    images.mkdir()
    (images / "photo.jpg").write_text("original")
    (downloads / "photo.jpg").write_text("newcomer")

    files.organize_files(cfg, directory=str(downloads), dry_run=False)
    assert (images / "photo.jpg").read_text() == "original"
    assert (images / "photo (2).jpg").read_text() == "newcomer"


def test_by_date_strategy(cfg):
    downloads = cfg["_downloads"]
    populate(downloads, ["snap.jpg"])
    plan = files.build_plan(downloads, "by_date")
    parts = Path(plan[0]["dst"]).parts
    assert parts[-3].isdigit()          # year
    assert "-" in parts[-2]             # 03-March


def test_find_files_by_pattern(cfg):
    downloads = cfg["_downloads"]
    populate(downloads, ["invoice-1.pdf", "invoice-2.pdf", "cat.jpg"])
    result = files.find_files(cfg, directory=str(downloads), pattern="invoice*")
    assert "invoice-1.pdf" in result and "cat.jpg" not in result


def test_find_files_by_content(cfg):
    downloads = cfg["_downloads"]
    (downloads / "notes.txt").write_text("the quarterly budget is attached")
    (downloads / "other.txt").write_text("nothing relevant here")
    result = files.find_files(cfg, directory=str(downloads), pattern="*.txt", contains="budget")
    assert "notes.txt" in result and "other.txt" not in result


def test_human_size():
    assert files.human_size(512) == "512 B"
    assert files.human_size(2048) == "2.0 KB"
    assert files.human_size(5 * 1024**3) == "5.0 GB"


def test_summarize_plan_empty():
    assert "already in order" in files.summarize_plan([])
