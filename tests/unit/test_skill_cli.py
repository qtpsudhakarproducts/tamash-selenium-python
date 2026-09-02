from tamash_selenium.cli import skill


def test_package_version_resolves():
    v = skill.get_package_version()
    assert v and v != "unknown"


def test_bundled_skill_files_present():
    assert skill.skill_resource_available()


def test_install_creates_both_targets(tmp_path):
    version = "9.9.9"
    for target in skill.TARGETS:
        result = skill.install_skill(target, tmp_path, version)
        assert result["action"] == "created"
        dest = tmp_path / target.project_dir
        assert (dest / "SKILL.md").is_file()
        assert (dest / "references" / "heal.md").is_file()
        assert (dest / "references" / "onboarding.md").is_file()
        assert skill.read_version_marker((dest / skill._MARKER_FILENAME).read_text()) == version


def test_state_reports_current_then_outdated(tmp_path):
    target = skill.TARGETS[0]
    skill.install_skill(target, tmp_path, "1.0.0")
    assert skill.skill_state(str(tmp_path), target, "1.0.0") == {"status": "current", "version": "1.0.0"}
    stale = skill.skill_state(str(tmp_path), target, "2.0.0")
    assert stale["status"] == "outdated" and stale["installed"] == "1.0.0" and stale["version"] == "2.0.0"


def test_state_absent_when_not_installed(tmp_path):
    assert skill.skill_state(str(tmp_path), skill.TARGETS[0], "1.0.0") == {"status": "absent"}


def test_reinstall_same_version_is_skipped(tmp_path):
    target = skill.TARGETS[0]
    skill.install_skill(target, tmp_path, "1.2.3")
    again = skill.install_skill(target, tmp_path, "1.2.3")
    assert again["action"] == "skipped"


def test_unmanaged_copy_is_flagged(tmp_path):
    target = skill.TARGETS[0]
    dest = tmp_path / target.project_dir
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("hand-written", encoding="utf-8")
    assert skill.skill_state(str(tmp_path), target, "1.0.0") == {"status": "unmanaged"}
    blocked = skill.install_skill(target, tmp_path, "1.0.0")
    assert blocked["action"] == "blocked"
    forced = skill.install_skill(target, tmp_path, "1.0.0", force=True)
    assert forced["action"] == "updated"


def test_dry_run_writes_nothing(tmp_path):
    target = skill.TARGETS[0]
    result = skill.install_skill(target, tmp_path, "1.0.0", dry_run=True)
    assert result["action"] == "created"
    assert not (tmp_path / target.project_dir).exists()
