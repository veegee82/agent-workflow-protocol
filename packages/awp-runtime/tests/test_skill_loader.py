"""Tests for awp.runtime.skill_loader."""

import zipfile
from pathlib import Path

import pytest

from awp.runtime.skill_loader import (
    SkillBundle,
    load_skill,
    load_external_skills,
)


@pytest.fixture
def tmp_path_factory_skills(tmp_path):
    """Create various skill fixtures."""
    return tmp_path


class TestLoadFromFile:
    def test_single_md_file(self, tmp_path):
        md = tmp_path / "my_skill.md"
        md.write_text("# My Skill\n\nSome content.", encoding="utf-8")

        bundle = load_skill(md)

        assert isinstance(bundle, SkillBundle)
        assert bundle.name == "my_skill"
        assert "# My Skill" in bundle.content
        assert bundle.references == {}

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            load_skill("/nonexistent/path.md")

    def test_unsupported_format_raises(self, tmp_path):
        txt = tmp_path / "skill.txt"
        txt.write_text("hello", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported skill format"):
            load_skill(txt)


class TestLoadFromDirectory:
    def test_directory_with_skill_md(self, tmp_path):
        skill_dir = tmp_path / "risk_analysis"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Risk Analysis\n\nAnalyze risk.", encoding="utf-8"
        )

        bundle = load_skill(skill_dir)

        assert bundle.name == "risk_analysis"
        assert "# Risk Analysis" in bundle.content

    def test_directory_with_references(self, tmp_path):
        skill_dir = tmp_path / "coding"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Coding Skill", encoding="utf-8")

        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "api_spec.md").write_text("API spec content", encoding="utf-8")

        examples_dir = skill_dir / "examples"
        examples_dir.mkdir()
        (examples_dir / "example1.py").write_text("print('hello')", encoding="utf-8")

        bundle = load_skill(skill_dir)

        assert bundle.name == "coding"
        assert "# Coding Skill" in bundle.content
        assert "references/api_spec.md" in bundle.references
        assert "examples/example1.py" in bundle.references
        # References should be appended to content
        assert "API spec content" in bundle.content
        assert "print('hello')" in bundle.content

    def test_directory_without_skill_md_raises(self, tmp_path):
        skill_dir = tmp_path / "empty_skill"
        skill_dir.mkdir()

        with pytest.raises(ValueError, match="does not contain SKILL.md"):
            load_skill(skill_dir)


class TestLoadFromArchive:
    def test_zip_archive(self, tmp_path):
        # Create a skill directory first
        skill_dir = tmp_path / "my_skill_src"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Archived Skill\n\nFrom ZIP.", encoding="utf-8"
        )
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "ref.md").write_text("Reference content", encoding="utf-8")

        # Create ZIP
        zip_path = tmp_path / "my_skill.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in skill_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(skill_dir))

        bundle = load_skill(zip_path)

        assert bundle.name == "my_skill"
        assert "# Archived Skill" in bundle.content
        assert "Reference content" in bundle.content

    def test_skill_extension(self, tmp_path):
        # .skill is just a ZIP with different extension
        skill_dir = tmp_path / "src"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Dot Skill", encoding="utf-8")

        skill_path = tmp_path / "domain.skill"
        with zipfile.ZipFile(skill_path, "w") as zf:
            zf.write(skill_dir / "SKILL.md", "SKILL.md")

        bundle = load_skill(skill_path)

        assert bundle.name == "domain"
        assert "# Dot Skill" in bundle.content

    def test_nested_archive(self, tmp_path):
        """Archive with files inside a single subdirectory."""
        inner_dir = tmp_path / "inner"
        inner_dir.mkdir()
        (inner_dir / "SKILL.md").write_text("# Nested", encoding="utf-8")

        zip_path = tmp_path / "nested.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(inner_dir / "SKILL.md", "inner/SKILL.md")

        bundle = load_skill(zip_path)
        assert "# Nested" in bundle.content

    def test_invalid_zip_raises(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_text("not a zip", encoding="utf-8")

        with pytest.raises(ValueError, match="Not a valid ZIP"):
            load_skill(bad)

    def test_zip_without_skill_md_raises(self, tmp_path):
        zip_path = tmp_path / "no_skill.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.md", "No SKILL.md here")

        with pytest.raises(ValueError, match="does not contain SKILL.md"):
            load_skill(zip_path)


class TestLoadExternalSkills:
    def test_load_multiple(self, tmp_path):
        md1 = tmp_path / "skill1.md"
        md1.write_text("# Skill 1", encoding="utf-8")

        md2 = tmp_path / "skill2.md"
        md2.write_text("# Skill 2", encoding="utf-8")

        bundles = load_external_skills([md1, md2])

        assert len(bundles) == 2
        assert bundles[0].name == "skill1"
        assert bundles[1].name == "skill2"

    def test_empty_list(self):
        assert load_external_skills([]) == []

    def test_mixed_formats(self, tmp_path):
        # MD file
        md = tmp_path / "file_skill.md"
        md.write_text("# File Skill", encoding="utf-8")

        # Directory
        dir_skill = tmp_path / "dir_skill"
        dir_skill.mkdir()
        (dir_skill / "SKILL.md").write_text("# Dir Skill", encoding="utf-8")

        bundles = load_external_skills([md, dir_skill])

        assert len(bundles) == 2
        assert bundles[0].name == "file_skill"
        assert bundles[1].name == "dir_skill"
