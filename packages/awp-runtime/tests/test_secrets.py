"""Tests for AWP secrets loader."""

from textwrap import dedent

import pytest

from awp.runtime.secrets import (
    load_secrets,
    _load_secrets_yaml,
    _load_dotenv,
    _resolve_template,
)


class TestResolveTemplate:
    def test_simple_template(self):
        result = _resolve_template("{{ env.MY_VAR }}", {"MY_VAR": "hello"})
        assert result == "hello"

    def test_no_template(self):
        result = _resolve_template("plain-value", {})
        assert result == "plain-value"

    def test_template_no_spaces(self):
        result = _resolve_template("{{env.MY_VAR}}", {"MY_VAR": "hello"})
        assert result == "hello"

    def test_missing_env_raises(self):
        with pytest.raises(ValueError, match="undefined variable.*MISSING_VAR"):
            _resolve_template("{{ env.MISSING_VAR }}", {})

    def test_mixed_text_and_template(self):
        result = _resolve_template(
            "prefix-{{ env.KEY }}-suffix",
            {"KEY": "middle"},
        )
        assert result == "prefix-middle-suffix"


class TestLoadDotenv:
    def test_basic(self, tmp_path):
        (tmp_path / ".env").write_text("KEY1=value1\nKEY2=value2\n")
        result = _load_dotenv(tmp_path)
        assert result == {"KEY1": "value1", "KEY2": "value2"}

    def test_quoted_values(self, tmp_path):
        (tmp_path / ".env").write_text("KEY=\"quoted\"\nKEY2='single'\n")
        result = _load_dotenv(tmp_path)
        assert result == {"KEY": "quoted", "KEY2": "single"}

    def test_comments_and_blanks(self, tmp_path):
        (tmp_path / ".env").write_text("# comment\n\nKEY=val\n")
        result = _load_dotenv(tmp_path)
        assert result == {"KEY": "val"}

    def test_no_env_file(self, tmp_path):
        result = _load_dotenv(tmp_path)
        assert result == {}


class TestLoadSecretsYaml:
    def test_basic(self, tmp_path):
        (tmp_path / "secrets.yaml").write_text(
            dedent("""\
            secrets:
              API_KEY: "sk-123"
              TOKEN: bearer-abc
        """)
        )
        result = _load_secrets_yaml(tmp_path, {})
        assert result == {"API_KEY": "sk-123", "TOKEN": "bearer-abc"}

    def test_env_template(self, tmp_path):
        (tmp_path / "secrets.yaml").write_text(
            dedent("""\
            secrets:
              DB_URL: "{{ env.PROD_DB }}"
        """)
        )
        result = _load_secrets_yaml(tmp_path, {"PROD_DB": "postgres://..."})
        assert result == {"DB_URL": "postgres://..."}

    def test_missing_env_template_raises(self, tmp_path):
        (tmp_path / "secrets.yaml").write_text(
            dedent("""\
            secrets:
              KEY: "{{ env.NOPE }}"
        """)
        )
        with pytest.raises(ValueError, match="NOPE"):
            _load_secrets_yaml(tmp_path, {})

    def test_no_file(self, tmp_path):
        result = _load_secrets_yaml(tmp_path, {})
        assert result == {}

    def test_no_secrets_key(self, tmp_path):
        (tmp_path / "secrets.yaml").write_text("other: value\n")
        result = _load_secrets_yaml(tmp_path, {})
        assert result == {}


class TestLoadSecrets:
    def test_priority_order(self, tmp_path, monkeypatch):
        """secrets.yaml wins over .env, which wins over os.environ."""
        monkeypatch.setenv("SHARED_KEY", "from-env")
        (tmp_path / ".env").write_text("SHARED_KEY=from-dotenv\n")
        (tmp_path / "secrets.yaml").write_text(
            dedent("""\
            secrets:
              SHARED_KEY: "from-yaml"
        """)
        )
        result = load_secrets(tmp_path)
        assert result["SHARED_KEY"] == "from-yaml"

    def test_dotenv_over_environ(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KEY", "from-env")
        (tmp_path / ".env").write_text("KEY=from-dotenv\n")
        result = load_secrets(tmp_path)
        assert result["KEY"] == "from-dotenv"

    def test_environ_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONLY_ENV", "env-value")
        result = load_secrets(tmp_path)
        assert result["ONLY_ENV"] == "env-value"

    def test_no_files(self, tmp_path):
        # Should not crash, returns at least os.environ
        result = load_secrets(tmp_path)
        assert isinstance(result, dict)
