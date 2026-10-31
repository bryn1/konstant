"""konstant.toml: defaults, fail-closed validation, workspace resolution."""
from __future__ import annotations

import pytest

from konstant import config


def test_defaults_without_a_file(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg.source is None
    assert cfg.base_url == "http://127.0.0.1:8470"
    assert cfg.db_path == tmp_path / "var" / "board.db"
    assert cfg.data["board"]["policy"]["verify_roles"] == ["verifier", "owner"]


def test_values_override(tmp_path):
    (tmp_path / "konstant.toml").write_text('[board]\nport = 9100\n[harness]\nenv = {A = "1"}\n')
    cfg = config.load(tmp_path)
    assert cfg.base_url.endswith(":9100") and cfg.data["harness"]["env"] == {"A": "1"}
    assert cfg.data["board"]["host"] == "127.0.0.1"


@pytest.mark.parametrize("text,needle", [
    ("[board]\nprot = 1\n", "unknown key 'board.prot'"),
    ("[bord]\n", "unknown key 'bord'"),
    ('[board]\nport = "8470"\n', "must be int"),
    ("[board]\nport = true\n", "must be int"),
    ("[gate]\nverify_after_close = 1\n", "must be bool"),
    ("[verify]\npath_roots = [1]\n", "list of strings"),
    ("[board\n", "konstant.toml"),
])
def test_malformed_config_raises(tmp_path, text, needle):
    (tmp_path / "konstant.toml").write_text(text)
    with pytest.raises(config.ConfigError, match=needle):
        config.load(tmp_path)


def test_find_home(tmp_path, monkeypatch):
    monkeypatch.delenv("KONSTANT_HOME", raising=False)
    (tmp_path / "konstant.toml").write_text("")
    deep = tmp_path / "projects" / "demo" / "src"
    deep.mkdir(parents=True)
    assert config.find_home(cwd=deep) == tmp_path.resolve()
    monkeypatch.setenv("KONSTANT_HOME", str(deep))
    assert config.find_home() == deep.resolve()
    assert config.find_home(str(tmp_path / "konstant.toml")) == tmp_path.resolve()


def test_no_workspace_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("KONSTANT_HOME", raising=False)
    with pytest.raises(config.ConfigError, match="no konstant workspace"):
        config.find_home(cwd=tmp_path)


def test_explicit_missing_config_is_an_error(tmp_path):
    with pytest.raises(config.ConfigError, match="not found"):
        config.load(tmp_path, str(tmp_path / "nope.toml"))
