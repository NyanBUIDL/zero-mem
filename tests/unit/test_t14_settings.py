"""T14 - learning-harness settings: closed schema, safe defaults, precedence, fail-safe, atomic writes.

Windows-safe: no POSIX modes or absolute-path assumptions; every file is UTF-8.
"""
from __future__ import annotations

import itertools
import os
from pathlib import Path

import pytest

from zero_mem import learning_settings as ls
from zero_mem.learning_settings import (
    INJECTION_MAX_CHARS_HARD_CAP, Settings, SettingsError, load_settings, parse_settings, resolve_injection,
)


@pytest.fixture
def path(tmp_path) -> Path:
    return tmp_path / "cfg" / "settings.toml"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- location and defaults
def test_settings_path_defaults_to_the_config_root_and_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv(ls.SETTINGS_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert ls.settings_path() == tmp_path / "xdg" / "zero-mem" / "settings.toml"
    monkeypatch.setenv(ls.SETTINGS_ENV, str(tmp_path / "other.toml"))
    assert ls.settings_path() == tmp_path / "other.toml"


def test_missing_file_gives_the_documented_safe_defaults(path):
    cfg = load_settings(path)
    assert cfg.valid and cfg.error is None
    assert (cfg.mode, cfg.max_proposals_per_day, cfg.allow_agent_proposals) == ("suggest", 20, True)
    assert (cfg.proposal_ttl_days, cfg.active_ttl_days) == (30, 0)
    assert cfg.injection_enabled is False and cfg.injection_max_chars == 2000
    assert cfg.kill_switch is False and cfg.deny_patterns == ()
    assert cfg.learning_enabled
    assert resolve_injection("p", "proj", cfg) == (False, 2000, ("rule", "decision", "gotcha"))


def test_empty_file_is_the_defaults(path):
    write(path, "")
    assert load_settings(path) == Settings()


def test_full_file_round_trips(path):
    write(path, """
[learning]
mode = "off"
max_proposals_per_day = 3
allow_agent_proposals = false
proposal_ttl_days = 7
active_ttl_days = 90

[injection]
enabled = true
max_chars = 500
types = ["rule", "persona"]

[injection.profiles."claude-code"]
enabled = false

[injection.projects."my.proj"]
max_chars = 100
types = ["devlog"]

[safety]
kill_switch = true
deny_patterns = ["internal-\\\\d+"]
""")
    cfg = load_settings(path)
    assert cfg.valid, cfg.error
    assert cfg.mode == "off" and cfg.max_proposals_per_day == 3 and cfg.allow_agent_proposals is False
    assert cfg.proposal_ttl_days == 7 and cfg.active_ttl_days == 90
    assert cfg.injection_enabled and cfg.injection_max_chars == 500 and cfg.injection_types == ("rule", "persona")
    assert cfg.profiles["claude-code"].enabled is False
    assert cfg.projects["my.proj"].types == ("devlog",)
    assert cfg.kill_switch and cfg.deny_patterns == ("internal-\\d+",)


# ---------------------------------------------------------------- closed schema
@pytest.mark.parametrize("body", [
    "[bogus]\nx = 1\n",
    "[learning]\nmode = \"loud\"\n",
    "[learning]\nmode = 1\n",
    "[learning]\nextra = 1\n",
    "[learning]\nmax_proposals_per_day = -1\n",
    "[learning]\nmax_proposals_per_day = 1001\n",
    "[learning]\nmax_proposals_per_day = true\n",
    "[learning]\nmax_proposals_per_day = 1.5\n",
    "[learning]\nproposal_ttl_days = 0\n",
    "[learning]\nactive_ttl_days = -2\n",
    "[learning]\nallow_agent_proposals = \"yes\"\n",
    "[injection]\nenabled = 1\n",
    "[injection]\nmax_chars = 8001\n",
    "[injection]\nmax_chars = 0\n",
    "[injection]\ntypes = [\"fact\"]\n",
    "[injection]\ntypes = \"rule\"\n",
    "[injection]\nunknown = true\n",
    "[injection.profiles.\"bad name\"]\nenabled = true\n",
    "[injection.profiles.p]\nbogus = 1\n",
    "[injection.projects.p]\nmax_chars = 9000\n",
    "[safety]\nkill_switch = \"true\"\n",
    "[safety]\ndeny_patterns = \"x\"\n",
    "[safety]\ndeny_patterns = [1]\n",
    "[safety]\ndeny_patterns = [\"(\"]\n",
    "[safety]\ndeny_patterns = [\"(a+)+$\"]\n",
    "[safety]\ndeny_patterns = [\"\"]\n",
    "learning = 3\n",
])
def test_schema_violations_fail_safe(path, body):
    write(path, body)
    cfg = load_settings(path)
    assert not cfg.valid and cfg.error
    assert cfg.mode == "off" and not cfg.learning_enabled
    assert resolve_injection("p", "proj", cfg) == (False, 0, ())


def test_deny_pattern_count_and_length_are_capped(path):
    too_many = ", ".join('"a%d"' % i for i in range(ls.MAX_DENY_PATTERNS + 1))
    write(path, f"[safety]\ndeny_patterns = [{too_many}]\n")
    assert not load_settings(path).valid
    write(path, '[safety]\ndeny_patterns = ["%s"]\n' % ("a" * (ls.MAX_DENY_PATTERN_CHARS + 1)))
    assert not load_settings(path).valid
    ok = ", ".join('"a%d"' % i for i in range(ls.MAX_DENY_PATTERNS))
    write(path, f"[safety]\ndeny_patterns = [{ok}]\n")
    assert load_settings(path).valid


def test_override_tables_are_capped(path):
    body = "".join(f'[injection.profiles."p{i}"]\nenabled = true\n' for i in range(ls.MAX_OVERRIDES + 1))
    write(path, body)
    assert not load_settings(path).valid


def test_a_catastrophic_pattern_is_refused_and_a_normal_one_matches_bounded_text():
    with pytest.raises(SettingsError):
        ls.check_deny_pattern("(x+x+)+y")
    cfg = Settings(deny_patterns=("secret-project-\\d+",))
    assert ls.matches_deny_pattern(cfg, "mentions SECRET-PROJECT-12 here")
    assert not ls.matches_deny_pattern(cfg, "nothing")
    huge = "a" * (ls.MAX_DENY_SCAN_CHARS + 10) + "secret-project-1"
    assert not ls.matches_deny_pattern(cfg, huge)  # only the bounded prefix is scanned


# ---------------------------------------------------------------- fail safe
def test_invalid_toml_unreadable_binary_and_oversized_files_fail_safe(path):
    for payload in (b"[learning\nmode=", b"\xff\xfe\x00bad", b"#" * (ls.MAX_SETTINGS_BYTES + 5)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        cfg = load_settings(path)
        assert not cfg.valid and cfg.mode == "off" and cfg.injection_enabled is False


def test_a_directory_in_place_of_the_file_fails_safe_and_never_raises(path):
    path.mkdir(parents=True)
    cfg = load_settings(path)
    assert not cfg.valid
    assert resolve_injection("p", None, cfg) == (False, 0, ())


def test_load_is_cached_but_follows_changes(path):
    write(path, '[learning]\nmode = "off"\n')
    assert load_settings(path).mode == "off"
    write(path, '[learning]\nmode = "suggest"\nmax_proposals_per_day = 5\n')
    assert load_settings(path).max_proposals_per_day == 5


# ---------------------------------------------------------------- auto_low_risk never auto-approves (phase 1)
def test_auto_low_risk_is_accepted_but_behaves_as_suggest(path):
    write(path, '[learning]\nmode = "auto_low_risk"\n')
    cfg = load_settings(path)
    assert cfg.valid and cfg.mode == "auto_low_risk"
    assert cfg.effective_mode == "suggest" and cfg.learning_enabled


# ---------------------------------------------------------------- precedence: every combination
def _cfg(g, pr, pj, kill=False):
    def ov(t):
        return None if t is None else ls.InjectionOverride(*t)

    return Settings(
        injection_enabled=g[0], injection_max_chars=g[1], injection_types=g[2],
        profiles={"prof": ov(pr)} if pr is not None else {},
        projects={"proj": ov(pj)} if pj is not None else {},
        kill_switch=kill)


_GLOBAL = (False, 2000, ("rule", "decision", "gotcha"))
_LAYERS = [None, (None, None, None), (True, None, None), (False, 100, ("persona",)), (True, 4000, ("devlog",)),
           (None, 50, None), (None, None, ("skill", "workflow"))]


@pytest.mark.parametrize("pr,pj", list(itertools.product(_LAYERS, _LAYERS)))
def test_precedence_project_over_profile_over_global_per_field(pr, pj):
    cfg = _cfg(_GLOBAL, pr, pj)
    enabled, max_chars, types = _GLOBAL
    for layer in (pr, pj):  # profile first, then project overrides it
        if layer is None:
            continue
        enabled = layer[0] if layer[0] is not None else enabled
        max_chars = layer[1] if layer[1] is not None else max_chars
        types = layer[2] if layer[2] is not None else types
    assert resolve_injection("prof", "proj", cfg) == (enabled, max_chars, types)


def test_unmatched_profile_or_project_fall_back_and_none_is_global():
    cfg = _cfg((True, 700, ("rule",)), (False, 10, ("persona",)), (True, 20, ("devlog",)))
    assert resolve_injection("other", "other", cfg) == (True, 700, ("rule",))
    assert resolve_injection(None, None, cfg) == (True, 700, ("rule",))
    assert resolve_injection("prof", None, cfg) == (False, 10, ("persona",))
    assert resolve_injection("prof", "proj", cfg) == (True, 20, ("devlog",))
    assert resolve_injection("other", "proj", cfg) == (True, 20, ("devlog",))


@pytest.mark.parametrize("pr,pj", list(itertools.product(_LAYERS, _LAYERS)))
def test_kill_switch_overrides_everything(pr, pj):
    cfg = _cfg((True, 8000, ("rule",)), pr, pj, kill=True)
    assert resolve_injection("prof", "proj", cfg) == (False, 0, ())


def test_max_chars_is_clamped_to_the_hard_cap_even_for_a_hand_built_settings():
    cfg = Settings(injection_enabled=True, injection_max_chars=10_000_000)
    assert resolve_injection("p", None, cfg).max_chars == INJECTION_MAX_CHARS_HARD_CAP


def test_resolve_injection_reads_the_settings_file_by_default(monkeypatch, path):
    write(path, '[injection]\nenabled = true\nmax_chars = 123\n')
    monkeypatch.setenv(ls.SETTINGS_ENV, str(path))
    assert resolve_injection("a", None) == (True, 123, ("rule", "decision", "gotcha"))


# ---------------------------------------------------------------- set / unset (dotted keys)
def test_set_validates_writes_atomically_and_reads_back(path):
    cfg = ls.set_value("learning.mode", "off", path)
    assert cfg.mode == "off" and path.is_file()
    ls.set_value("learning.max_proposals_per_day", "5", path)
    ls.set_value("injection.enabled", "true", path)
    ls.set_value("injection.types", "rule, gotcha", path)
    ls.set_value("injection.profiles.claude-code.max_chars", "300", path)
    ls.set_value("injection.projects.my.proj.enabled", "false", path)
    ls.set_value("safety.deny_patterns", '["a.b", "c"]', path)
    cfg = load_settings(path)
    assert cfg.valid and cfg.max_proposals_per_day == 5 and cfg.injection_enabled
    assert cfg.injection_types == ("rule", "gotcha")
    assert cfg.profiles["claude-code"].max_chars == 300 and cfg.projects["my.proj"].enabled is False
    assert cfg.deny_patterns == ("a.b", "c")
    leftovers = [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


@pytest.mark.parametrize("key,value", [
    ("learning.mode", "loud"), ("learning.max_proposals_per_day", "many"), ("learning.max_proposals_per_day", "-3"),
    ("learning.allow_agent_proposals", "maybe"), ("injection.max_chars", "8001"), ("injection.types", "fact"),
    ("injection.profiles.x.max_chars", "0"), ("injection.projects.bad name.enabled", "true"),
    ("safety.deny_patterns", "not-json"), ("safety.deny_patterns", '["(a+)+"]'), ("safety.deny_patterns", '{"a": 1}'),
    ("nope.key", "1"), ("learning.nope", "1"), ("", "1"), ("injection.profiles.x", "1"),
])
def test_set_rejects_bad_keys_and_values_without_touching_the_file(path, key, value):
    ls.set_value("learning.mode", "suggest", path)
    before = path.read_bytes()
    with pytest.raises(SettingsError):
        ls.set_value(key, value, path)
    assert path.read_bytes() == before


def test_set_refuses_to_overwrite_an_unusable_file(path):
    write(path, "[learning\n")
    before = path.read_bytes()
    with pytest.raises(SettingsError):
        ls.set_value("learning.mode", "off", path)
    assert path.read_bytes() == before


def test_unset_removes_a_key_prunes_empty_tables_and_reports_missing(path):
    ls.set_value("injection.profiles.a.enabled", "true", path)
    ls.set_value("learning.mode", "off", path)
    cfg, removed = ls.unset_value("injection.profiles.a.enabled", path)
    assert removed and cfg.profiles == {}
    assert "injection" not in path.read_text(encoding="utf-8")
    _cfg2, removed = ls.unset_value("injection.profiles.a.enabled", path)
    assert not removed
    ls.set_value("injection.projects.p.max_chars", "9", path)
    cfg, removed = ls.unset_value("injection.projects.p", path)  # a whole override
    assert removed and cfg.projects == {}
    cfg, removed = ls.unset_value("learning.mode", path)
    assert removed and cfg.mode == "suggest"


def test_unset_on_a_missing_file_is_a_noop(path):
    cfg, removed = ls.unset_value("learning.mode", path)
    assert not removed and cfg.valid and not path.exists()


def test_rendered_toml_escapes_hostile_strings_and_round_trips():
    import tomllib

    nasty = ['quo"te', "back\\slash", "tab\tnew\nline", "\x7f\x01ctl", "unié\U0001f600"]
    doc = {"safety": {"deny_patterns": nasty}}
    text = ls.render_toml(doc)
    assert tomllib.loads(text)["safety"]["deny_patterns"] == nasty


def test_failed_replace_leaves_the_old_file_intact_and_no_temp_files(path, monkeypatch):
    ls.set_value("learning.mode", "off", path)
    before = path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "disk full")))
    with pytest.raises(SettingsError):
        ls.set_value("learning.mode", "suggest", path)
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_replace_uses_the_transient_retry(path, monkeypatch):
    """DEF-090: a transient sharing denial on os.replace is retried, not surfaced."""
    from src.corpus import _fsretry

    monkeypatch.setattr(_fsretry, "_sleep", lambda _s: None)
    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(13, "sharing violation")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    cfg = ls.set_value("learning.mode", "off", path)
    assert cfg.mode == "off" and calls["n"] == 3

