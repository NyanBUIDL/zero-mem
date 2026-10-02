"""T20 - the ``[sharing]`` settings table (closed schema, safe defaults, kill switch, fail safe). Needs no cryptography."""
from __future__ import annotations

import pytest

from zero_mem import learning_settings as ls


def load(tmp_path, text):
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return ls.load_settings(path)


def test_defaults_are_off_and_safe(tmp_path):
    cfg = ls.load_settings(tmp_path / "missing.toml")
    assert cfg.sharing_enabled is False and cfg.sharing_active is False
    assert cfg.max_pull_sources == 200
    assert cfg.max_source_bytes == 1024 * 1024
    assert cfg.max_total_bytes == 64 * 1024 * 1024
    assert cfg.allow_public_bind is False and cfg.import_into_recall is False and cfg.announce_label is False


def test_enabled_and_values_parse(tmp_path):
    cfg = load(tmp_path, "[sharing]\nenabled = true\nmax_pull_sources = 5\nmax_source_bytes = 2048\n"
                         "max_total_bytes = 4096\nimport_into_recall = true\nannounce_label = true\n")
    assert cfg.valid and cfg.sharing_enabled and cfg.sharing_active
    assert (cfg.max_pull_sources, cfg.max_source_bytes, cfg.max_total_bytes) == (5, 2048, 4096)
    assert cfg.import_into_recall and cfg.announce_label and not cfg.allow_public_bind
    assert cfg.as_dict()["sharing"]["enabled"] is True


@pytest.mark.parametrize("body", [
    "[sharing]\nenabled = \"yes\"\n", "[sharing]\nunknown = 1\n", "[sharing]\nmax_pull_sources = 0\n",
    "[sharing]\nmax_source_bytes = -1\n", "[sharing]\nmax_total_bytes = 99999999999999\n",
    "[sharing]\nallow_public_bind = 1\n", "sharing = 3\n",
])
def test_invalid_sharing_fails_safe_to_off(tmp_path, body):
    cfg = load(tmp_path, body)
    assert cfg.valid is False and cfg.sharing_enabled is False and cfg.sharing_active is False


def test_kill_switch_disables_sharing(tmp_path):
    cfg = load(tmp_path, "[sharing]\nenabled = true\n[safety]\nkill_switch = true\n")
    assert cfg.sharing_enabled is True and cfg.sharing_active is False


def test_set_unset_roundtrip_and_known_keys(tmp_path):
    path = tmp_path / "cfg" / "settings.toml"
    cfg = ls.set_value("sharing.enabled", "true", path)
    assert cfg.sharing_enabled
    cfg = ls.set_value("sharing.max_pull_sources", "7", path)
    assert cfg.max_pull_sources == 7
    assert "[sharing]" in path.read_text(encoding="utf-8")
    cfg, removed = ls.unset_value("sharing.enabled", path)
    assert removed and not cfg.sharing_enabled
    with pytest.raises(ls.SettingsError):
        ls.set_value("sharing.max_pull_sources", "0", path)
    assert "sharing.import_into_recall" in ls.KNOWN_KEYS
