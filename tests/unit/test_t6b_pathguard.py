"""T6b - the ``memory_ingest`` path policy (``src.integration.m6w.pathguard``) and the schema/validator contract."""
from __future__ import annotations

import os

import pytest

from src.integration.m6w import PathGuard, RootsConfigError, contracts as c, normalize_roots

# Python 3.13 on Windows no longer treats "/etc/passwd" as absolute: build platform-absolute outside paths.
ABS_PASSWD = os.path.abspath(os.sep + "etc" + os.sep + "passwd")
ABS_ETC = os.path.abspath(os.sep + "etc")
ABS_ROOT = os.path.abspath(os.sep)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "a.md").write_text("# a\n", encoding="utf-8", newline="\n")
    (root / "sub" / "deep" / "b.txt").write_text("b", encoding="utf-8", newline="\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.txt").write_text("o", encoding="utf-8", newline="\n")
    return root, outside


def guard(root, reserved=()):
    return PathGuard(normalize_roots([root]), reserved)


# ----------------------------------------------------------------------------------------------- roots
@pytest.mark.parametrize("bad", ["", "  ", "relative", "~", "~/x", "/definitely/not/here", "/", None, 5])
def test_unusable_roots_are_refused_without_echoing_them(bad):
    with pytest.raises(RootsConfigError) as exc:
        normalize_roots([bad])
    message = str(exc.value)
    assert "allow-root" in message
    if isinstance(bad, str) and bad.strip():
        assert bad not in message  # the operator's value is never echoed


def test_a_file_is_not_a_root_and_duplicates_collapse(tree):
    root, _ = tree
    with pytest.raises(RootsConfigError):
        normalize_roots([root / "a.md"])
    assert len(normalize_roots([root, str(root) + "/", root / "sub" / ".."])) == 1


# ----------------------------------------------------------------------------------------------- check
def test_files_and_folders_under_the_root_are_accepted(tree):
    root, _ = tree
    g = guard(root)
    for target in (root, root / "a.md", root / "sub", root / "sub" / "deep" / "b.txt", str(root) + "/sub/../a.md"):
        verdict = g.check(str(target))
        assert verdict.ok, (target, verdict)
    assert g.check(str(root / "sub" / ".." / "a.md")).path == (root / "a.md").resolve()


@pytest.mark.parametrize("make,code", [
    (lambda root, out: out / "o.txt", c.DENY_PATH_OUTSIDE_ALLOWLIST),
    (lambda root, out: out, c.DENY_PATH_OUTSIDE_ALLOWLIST),
    (lambda root, out: root.parent, c.DENY_PATH_OUTSIDE_ALLOWLIST),
    (lambda root, out: str(root) + "-sibling", c.DENY_PATH_OUTSIDE_ALLOWLIST),
    (lambda root, out: str(root) + "/../outside/o.txt", c.DENY_PATH_OUTSIDE_ALLOWLIST),
    (lambda root, out: ABS_PASSWD, c.DENY_PATH_OUTSIDE_ALLOWLIST),
    (lambda root, out: ABS_ROOT, c.DENY_PATH_OUTSIDE_ALLOWLIST),
    (lambda root, out: str(root) + "/missing.md", c.PATH_NOT_FOUND),
    (lambda root, out: str(root) + "/sub/missing/x.md", c.PATH_NOT_FOUND),
])
def test_outside_missing_and_traversal(tree, make, code):
    root, out = tree
    verdict = guard(root).check(str(make(root, out)))
    assert not verdict.ok and verdict.code == code and verdict.path is None


@pytest.mark.parametrize("raw", ["a.md", "./a.md", "../x", "~/a.md", ""])
def test_relative_paths_are_invalid_not_resolved(tree, raw):
    root, _ = tree
    verdict = guard(root).check(raw)
    assert not verdict.ok and verdict.status == c.INVALID


@pytest.mark.parametrize("raw", ["/tmp/x\x00y", "/tmp/x\ny", "/tmp/" + "a" * 5000, None, 5, ["/tmp"]])
def test_malformed_paths_are_invalid(tree, raw):
    root, _ = tree
    verdict = guard(root).check(raw)
    assert not verdict.ok and verdict.status == c.INVALID and verdict.code == c.INVALID_ARGUMENTS


def test_symlinks_are_refused_wherever_they_sit_below_the_root(tree):
    root, out = tree
    (root / "file-link").symlink_to(out / "o.txt")
    (root / "dir-link").symlink_to(out, target_is_directory=True)
    (root / "sub" / "deep" / "inner-link").symlink_to(root / "a.md")  # a link to something INSIDE is refused too
    (root / "loop").symlink_to(root, target_is_directory=True)
    g = guard(root)
    for target in ("file-link", "dir-link", "dir-link/o.txt", "sub/deep/inner-link", "loop", "loop/a.md"):
        verdict = g.check(str(root / target))
        assert not verdict.ok and verdict.code == c.DENY_SYMLINK, (target, verdict)
    (root / "dangling").symlink_to(root / "nowhere")
    assert guard(root).check(str(root / "dangling")).code == c.DENY_SYMLINK


def test_a_root_given_through_a_symlink_works_but_the_alias_cannot_be_used_to_escape(tree, tmp_path):
    root, out = tree
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    g = PathGuard(normalize_roots([alias]), ())
    assert g.check(str(alias / "a.md")).ok and g.check(str(root / "a.md")).ok  # either spelling of the root
    assert g.check(str(alias)).path == root.resolve()  # the REAL path is what gets ingested
    assert g.check(str(out / "o.txt")).code == c.DENY_PATH_OUTSIDE_ALLOWLIST


def test_the_memory_store_is_reserved_whether_inside_contains_or_equals(tree, tmp_path):
    root, _ = tree
    store = root / "sub" / "store"
    store.mkdir()
    (store / "events.jsonl").write_text("{}\n", encoding="utf-8", newline="\n")
    g = guard(root, reserved=[store])
    for target in (store, store / "events.jsonl", root, root / "sub"):
        verdict = g.check(str(target))
        assert not verdict.ok and verdict.code == c.DENY_PATH_RESERVED, (target, verdict)
    assert g.check(str(root / "a.md")).ok
    assert g.check(str(root / "sub" / "deep")).ok


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo is POSIX-only; Windows has no FIFO primitive")
def test_only_regular_files_and_folders_can_be_ingested(tree):
    root, _ = tree
    fifo = root / "pipe"
    os.mkfifo(fifo)
    verdict = guard(root).check(str(fifo))
    assert not verdict.ok and verdict.code == c.UNSUPPORTED_PATH_TYPE


def test_no_roots_means_nothing_is_allowed(tree):
    root, _ = tree
    verdict = PathGuard([], ()).check(str(root / "a.md"))
    assert not verdict.ok and verdict.status == c.DENIED and verdict.code == c.DENY_NO_ALLOWED_ROOTS


def test_refusals_never_contain_a_path(tree):
    root, out = tree
    g = guard(root)
    for target in (out / "o.txt", root / "missing", ABS_PASSWD):
        verdict = g.check(str(target))
        assert str(root) not in repr(verdict) and str(out) not in repr(verdict)


# ----------------------------------------------------------------------------------------------- schema <-> validator
def _sample(prop):
    if "enum" in prop:
        return prop["enum"][0]
    if prop["type"] == "string":
        if prop.get("pattern") == c.PROJECT_ID_PATTERN:
            return "proj"
        if prop.get("pattern") == c.NAME_PATTERN:
            return "name"
        return "x" * max(1, prop.get("minLength", 1))
    if prop["type"] == "integer":
        return prop["minimum"]
    if prop["type"] == "array":
        return [_sample(prop["items"])]
    raise AssertionError(prop)


@pytest.mark.parametrize("tool", list(c.READ_TOOLS + c.WRITE_TOOLS))
def test_the_validator_enforces_exactly_what_the_schema_advertises(tool):
    schema = c.input_schema(tool)
    props = schema["properties"]
    minimal = {name: _sample(props[name]) for name in schema.get("required", [])}
    assert c.validate_arguments(tool, minimal) is None
    for name in schema.get("required", []):
        short = {k: v for k, v in minimal.items() if k != name}
        assert c.validate_arguments(tool, short)[0] == c.SCHEMA_VIOLATION
    assert c.validate_arguments(tool, {**minimal, "zzz": 1})[0] == c.UNKNOWN_ARGUMENT
    for name, prop in props.items():
        base = {**minimal}
        # every advertised property accepts a sample value
        base[name] = _sample(prop)
        assert c.validate_arguments(tool, base) is None, (tool, name)
        if prop["type"] == "integer":
            assert c.validate_arguments(tool, {**base, name: prop["maximum"]}) is None
            assert c.validate_arguments(tool, {**base, name: prop["maximum"] + 1})[0] == c.SCHEMA_VIOLATION
            assert c.validate_arguments(tool, {**base, name: prop["minimum"] - 1})[0] == c.SCHEMA_VIOLATION
            assert c.validate_arguments(tool, {**base, name: True})[0] == c.SCHEMA_VIOLATION
            assert c.validate_arguments(tool, {**base, name: float(prop["minimum"])})[0] == c.SCHEMA_VIOLATION
        elif prop["type"] == "string":
            filler = "p" if prop.get("pattern") in (c.PROJECT_ID_PATTERN, c.NAME_PATTERN) else "x"
            if "enum" not in prop:
                assert c.validate_arguments(tool, {**base, name: filler * prop["maxLength"]}) is None, (tool, name)
                assert c.validate_arguments(tool, {**base, name: filler * (prop["maxLength"] + 1)})[0] == c.SCHEMA_VIOLATION
            else:
                assert c.validate_arguments(tool, {**base, name: "nope"})[0] == c.SCHEMA_VIOLATION
            assert c.validate_arguments(tool, {**base, name: 5})[0] == c.SCHEMA_VIOLATION
            assert c.validate_arguments(tool, {**base, name: None})[0] == c.SCHEMA_VIOLATION
        elif prop["type"] == "array":
            assert c.validate_arguments(tool, {**base, name: []})[0] == c.SCHEMA_VIOLATION
            assert c.validate_arguments(tool, {**base, name: ["nope"]})[0] == c.SCHEMA_VIOLATION
            assert c.validate_arguments(tool, {**base, name: "persona"})[0] == c.SCHEMA_VIOLATION
            full = [prop["items"]["enum"][0]] * prop["maxItems"]
            assert c.validate_arguments(tool, {**base, name: full}) is None
            assert c.validate_arguments(tool, {**base, name: full + full[:1]})[0] == c.SCHEMA_VIOLATION


def test_validation_messages_never_echo_the_value():
    secret = "sk-" + "ant-api03-" + "z" * 40
    for tool, args in ((c.TOOL_ADD, {"text": secret, "memory_type": secret, "scope": "private"}),
                       (c.TOOL_RECALL, {"query": secret, "limit": secret}),
                       (c.TOOL_FORGET, {secret: 1})):
        problem = c.validate_arguments(tool, args)
        assert problem is not None and secret not in problem[1]
    assert len(c.validate_arguments(c.TOOL_FORGET, {"x" * 500: 1})[1]) < 80


def test_authority_keys_win_over_schema_errors():
    assert c.authority_violation({"requesting_profile_id": "codex"})[0] == c.DENY_IDENTITY_PINNED
    assert c.authority_violation({"grants": []})[0] == c.DENY_SCOPE_NOT_CALLER_CONTROLLED
    assert c.authority_violation({"text": "x", "scope": "private"}) is None
