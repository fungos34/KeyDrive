"""
Test update deployment filtering.

CHG-20251221-004: Verify that development files are properly excluded from deployment.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.constants import FileNames


class TestDeploymentExcludePatterns:
    """Test DEPLOYMENT_EXCLUDE_PATTERNS constant."""

    def test_patterns_list_exists(self):
        """Verify DEPLOYMENT_EXCLUDE_PATTERNS attribute exists."""
        assert hasattr(FileNames, "DEPLOYMENT_EXCLUDE_PATTERNS")
        patterns = FileNames.DEPLOYMENT_EXCLUDE_PATTERNS
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_patterns_include_common_dev_files(self):
        """Verify common development files are in exclusion list."""
        patterns = FileNames.DEPLOYMENT_EXCLUDE_PATTERNS

        # Git-related
        assert ".git" in patterns
        assert ".gitignore" in patterns
        assert ".github" in patterns

        # Python caches
        assert "__pycache__" in patterns
        assert "*.pyc" in patterns

        # IDE/Editor
        assert ".vscode" in patterns
        assert ".idea" in patterns

        # Tests
        assert "tests" in patterns

        # Virtual environments
        assert ".venv" in patterns or "venv" in patterns

        # BUG-20260102-001: Helper files (agent instructions)
        assert "helper" in patterns
        assert "helper_instruction.txt" in patterns

        # BUG-20260102-004: Update temp directory (prevents recursion)
        assert "_update_tmp" in patterns

    def test_readme_exception_pattern(self):
        """Verify README.md has exception pattern."""
        patterns = FileNames.DEPLOYMENT_EXCLUDE_PATTERNS

        # Should exclude *.md but keep README.md
        assert "*.md" in patterns
        assert "!README.md" in patterns


class TestShouldExcludeFromDeployment:
    """Test should_exclude_from_deployment function."""

    @pytest.fixture
    def temp_base(self):
        """Create temporary base directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        # Cleanup
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_git_directory_excluded(self, temp_base):
        """Test .git directory is excluded."""
        from scripts.update import should_exclude_from_deployment

        git_dir = temp_base / ".git"
        assert should_exclude_from_deployment(git_dir, temp_base) is True

    def test_github_directory_excluded(self, temp_base):
        """Test .github directory is excluded."""
        from scripts.update import should_exclude_from_deployment

        github_dir = temp_base / ".github"
        assert should_exclude_from_deployment(github_dir, temp_base) is True

    def test_pycache_directory_excluded(self, temp_base):
        """Test __pycache__ directory is excluded."""
        from scripts.update import should_exclude_from_deployment

        pycache_dir = temp_base / "scripts" / "__pycache__"
        assert should_exclude_from_deployment(pycache_dir, temp_base) is True

    def test_pyc_file_excluded(self, temp_base):
        """Test .pyc files are excluded."""
        from scripts.update import should_exclude_from_deployment

        pyc_file = temp_base / "test.pyc"
        assert should_exclude_from_deployment(pyc_file, temp_base) is True

    def test_tests_directory_excluded(self, temp_base):
        """Test tests directory is excluded."""
        from scripts.update import should_exclude_from_deployment

        tests_dir = temp_base / "tests"
        assert should_exclude_from_deployment(tests_dir, temp_base) is True

    def test_venv_directory_handling(self, temp_base):
        """Test virtual environment directories handling.

        CHG-20260102-007: .venv is NOW deployed (dependency shipping policy).
        Only 'venv' (alternate name) is excluded.
        """
        from scripts.update import should_exclude_from_deployment

        # .venv should NOT be excluded (deployed for portable dependencies)
        venv_dir = temp_base / ".venv"
        assert should_exclude_from_deployment(venv_dir, temp_base) is False

        # 'venv' (alternate name) should still be excluded
        venv_dir2 = temp_base / "venv"
        assert should_exclude_from_deployment(venv_dir2, temp_base) is True

    def test_vscode_directory_excluded(self, temp_base):
        """Test .vscode directory is excluded."""
        from scripts.update import should_exclude_from_deployment

        vscode_dir = temp_base / ".vscode"
        assert should_exclude_from_deployment(vscode_dir, temp_base) is True

    def test_helper_directory_excluded(self, temp_base):
        """Test helper directory is excluded (BUG-20260102-001)."""
        from scripts.update import should_exclude_from_deployment

        helper_dir = temp_base / "helper"
        assert should_exclude_from_deployment(helper_dir, temp_base) is True

    def test_helper_instruction_txt_excluded(self, temp_base):
        """Test helper_instruction.txt file is excluded (BUG-20260102-001)."""
        from scripts.update import should_exclude_from_deployment

        helper_file = temp_base / "helper_instruction.txt"
        assert should_exclude_from_deployment(helper_file, temp_base) is True

    def test_update_tmp_directory_excluded(self, temp_base):
        """Test _update_tmp directory is excluded (BUG-20260102-004)."""
        from scripts.update import should_exclude_from_deployment

        update_tmp_dir = temp_base / "_update_tmp"
        assert should_exclude_from_deployment(update_tmp_dir, temp_base) is True

    def test_python_script_included(self, temp_base):
        """Test .py files are included (not excluded)."""
        from scripts.update import should_exclude_from_deployment

        py_file = temp_base / "scripts" / "mount.py"
        assert should_exclude_from_deployment(py_file, temp_base) is False

    def test_core_directory_included(self, temp_base):
        """Test core directory is included."""
        from scripts.update import should_exclude_from_deployment

        core_dir = temp_base / "core"
        assert should_exclude_from_deployment(core_dir, temp_base) is False

    def test_scripts_directory_included(self, temp_base):
        """Test scripts directory is included."""
        from scripts.update import should_exclude_from_deployment

        scripts_dir = temp_base / "scripts"
        assert should_exclude_from_deployment(scripts_dir, temp_base) is False

    def test_markdown_excluded_except_readme(self, temp_base):
        """Test .md files excluded except README.md."""
        from scripts.update import should_exclude_from_deployment

        # Generic markdown should be excluded
        doc_md = temp_base / "CONTRIBUTING.md"
        assert should_exclude_from_deployment(doc_md, temp_base) is True

        # README.md should be kept (exception pattern)
        readme_md = temp_base / "README.md"
        # Note: The exception pattern "!README.md" should make this False
        # But current implementation may need refinement for negation
        # This tests current behavior
        result = should_exclude_from_deployment(readme_md, temp_base)
        # Due to exception pattern, should be kept (False)
        assert result is False

    def test_nested_pycache_excluded(self, temp_base):
        """Test __pycache__ in nested directories is excluded."""
        from scripts.update import should_exclude_from_deployment

        nested_pycache = temp_base / "core" / "submodule" / "__pycache__"
        assert should_exclude_from_deployment(nested_pycache, temp_base) is True

    def test_pytest_cache_excluded(self, temp_base):
        """Test .pytest_cache directory is excluded."""
        from scripts.update import should_exclude_from_deployment

        pytest_cache = temp_base / ".pytest_cache"
        assert should_exclude_from_deployment(pytest_cache, temp_base) is True


class TestCreateDeploymentIgnoreFunction:
    """Test create_deployment_ignore_function."""

    @pytest.fixture
    def temp_base(self):
        """Create temporary base directory with structure."""
        temp_dir = Path(tempfile.mkdtemp())

        # Create directory structure
        (temp_dir / "scripts").mkdir()
        (temp_dir / "core").mkdir()
        (temp_dir / ".git").mkdir()
        (temp_dir / "__pycache__").mkdir()
        (temp_dir / "tests").mkdir()

        # Create files
        (temp_dir / "scripts" / "mount.py").write_text("# mount script")
        (temp_dir / "core" / "config.py").write_text("# config module")
        (temp_dir / ".gitignore").write_text("*.pyc")
        (temp_dir / "test.pyc").write_text("")
        (temp_dir / "README.md").write_text("# README")
        (temp_dir / "CONTRIBUTING.md").write_text("# Contributing")

        yield temp_dir

        # Cleanup
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_ignore_function_returns_correct_list(self, temp_base):
        """Test ignore function returns list of excluded names."""
        from scripts.update import create_deployment_ignore_function

        ignore_func = create_deployment_ignore_function(temp_base)

        # Test on root directory
        names = [".git", "scripts", "core", "__pycache__", "tests", "README.md", ".gitignore"]
        ignored = ignore_func(str(temp_base), names)

        # Should ignore: .git, __pycache__, tests, .gitignore
        assert ".git" in ignored
        assert "__pycache__" in ignored
        assert "tests" in ignored
        assert ".gitignore" in ignored

        # Should NOT ignore: scripts, core, README.md
        assert "scripts" not in ignored
        assert "core" not in ignored
        assert "README.md" not in ignored

    def test_ignore_function_with_copytree(self, temp_base):
        """Test ignore function works with shutil.copytree."""
        from scripts.update import create_deployment_ignore_function

        ignore_func = create_deployment_ignore_function(temp_base)

        dest_dir = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(temp_base, dest_dir, dirs_exist_ok=True, ignore=ignore_func)

            # Check excluded items are NOT copied
            assert not (dest_dir / ".git").exists()
            assert not (dest_dir / "__pycache__").exists()
            assert not (dest_dir / "tests").exists()
            assert not (dest_dir / ".gitignore").exists()
            assert not (dest_dir / "test.pyc").exists()
            assert not (dest_dir / "CONTRIBUTING.md").exists()

            # Check included items ARE copied
            assert (dest_dir / "scripts").exists()
            assert (dest_dir / "core").exists()
            assert (dest_dir / "scripts" / "mount.py").exists()
            assert (dest_dir / "core" / "config.py").exists()
            assert (dest_dir / "README.md").exists()

        finally:
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)


class TestFilteringIntegration:
    """Integration tests for filtering in update workflow."""

    def test_filtered_copy_reduces_size(self):
        """Test that filtering significantly reduces deployed size."""
        from scripts.update import create_deployment_ignore_function

        # Create source with dev files
        src_dir = Path(tempfile.mkdtemp())
        try:
            # Create substantial dev content
            (src_dir / ".git").mkdir()
            (src_dir / ".git" / "objects").mkdir()
            for i in range(100):
                (src_dir / ".git" / "objects" / f"obj{i}").write_text("x" * 1000)

            (src_dir / "tests").mkdir()
            for i in range(50):
                (src_dir / "tests" / f"test_{i}.py").write_text("# test" * 100)

            (src_dir / "scripts").mkdir()
            (src_dir / "scripts" / "mount.py").write_text("# essential")

            # Copy without filtering
            dest_unfiltered = Path(tempfile.mkdtemp())
            shutil.copytree(src_dir, dest_unfiltered, dirs_exist_ok=True)
            unfiltered_count = sum(1 for _ in dest_unfiltered.rglob("*") if _.is_file())
            shutil.rmtree(dest_unfiltered)

            # Copy with filtering
            dest_filtered = Path(tempfile.mkdtemp())
            ignore_func = create_deployment_ignore_function(src_dir)
            shutil.copytree(src_dir, dest_filtered, dirs_exist_ok=True, ignore=ignore_func)
            filtered_count = sum(1 for _ in dest_filtered.rglob("*") if _.is_file())

            # Filtered should be significantly smaller
            assert filtered_count < unfiltered_count
            # Should have removed at least 100 files (.git objects + tests)
            assert (unfiltered_count - filtered_count) >= 100

            # Essential file should still be there
            assert (dest_filtered / "scripts" / "mount.py").exists()

            shutil.rmtree(dest_filtered)

        finally:
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)

    def test_no_pycache_in_deployment(self):
        """Test that no __pycache__ directories exist after filtering."""
        from scripts.update import create_deployment_ignore_function

        src_dir = Path(tempfile.mkdtemp())
        try:
            # Create structure with __pycache__
            (src_dir / "core").mkdir()
            (src_dir / "core" / "__pycache__").mkdir()
            (src_dir / "core" / "__pycache__" / "config.cpython-310.pyc").write_text("")
            (src_dir / "core" / "config.py").write_text("# config")

            (src_dir / "scripts").mkdir()
            (src_dir / "scripts" / "__pycache__").mkdir()
            (src_dir / "scripts" / "__pycache__" / "mount.cpython-310.pyc").write_text("")
            (src_dir / "scripts" / "mount.py").write_text("# mount")

            # Copy with filtering
            dest_dir = Path(tempfile.mkdtemp())
            ignore_func = create_deployment_ignore_function(src_dir)
            shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True, ignore=ignore_func)

            # Verify no __pycache__ directories exist
            pycache_dirs = list(dest_dir.rglob("__pycache__"))
            assert len(pycache_dirs) == 0

            # Verify .py files ARE present
            assert (dest_dir / "core" / "config.py").exists()
            assert (dest_dir / "scripts" / "mount.py").exists()

            shutil.rmtree(dest_dir)

        finally:
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)
