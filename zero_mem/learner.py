"""Deterministic learner: turn what a USER said in agent sessions into PROPOSALS (never active memory).

No LLM, no network, no dependencies. Precision over recall: a missed rule costs the owner one ``zero-mem propose``;
a wrong proposal costs review time and trust.

Sources (all produce :class:`Message` objects whose ``text`` is USER-authored):

* a Claude Code transcript JSONL (``{"type": "user", "message": {...}}``; tool results, assistant turns, sidechain
  (sub-agent) prompts, meta lines and injected ``<system-reminder>`` blocks are NOT user statements),
* a generic chat JSONL / JSON array (``{"role", "content"}``) and plain ``User: ...`` / ``Assistant: ...`` logs,
* git history (commit messages; commits written by an agent are skipped: verified outranks self-report),
* a Claude Code hook payload (``{"transcript_path", "session_id", "cwd"}``).

Extraction splits user text into sentences and keeps only instruction / correction / decision / gotcha statements
(English and Vietnamese cues). It drops questions, hypotheticals, first-person self-talk, reported speech, quoted or
pasted code / logs / tool output, very short or very long sentences, sentences with a secret (the normal pre-scan) and
sentences matching the owner's ``safety.deny_patterns``.

Everything goes through :meth:`zero_mem.memory.Memory.propose` with ``source="learner"``, so the owner's settings
(mode, kill switch, daily limit, deny patterns) apply, duplicates merge (``seen`` counter) and nothing is active until
``zero-mem review approve``. Re-running over the same input is idempotent: processed ``(session, line, sentence)`` keys
are remembered in ``learner-state-<profile>.json`` in the data root.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from . import learning_settings as ls

MIN_CHARS = 12
MAX_CHARS = 300
MIN_WORDS = 3
EVIDENCE_QUOTE_CHARS = 200
DEFAULT_MAX_PER_RUN = 10
HARD_MAX_PER_RUN = 100
MAX_MESSAGE_CHARS = 20_000
#: A user message longer than this is a pasted document / briefing, not a correction: skipped. At most MAX_PER_MESSAGE
#: candidates come out of one message.
MAX_PROCESS_CHARS = 4_000
MAX_PER_MESSAGE = 5
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_STATE_KEYS = 50_000
MAX_GIT_COMMITS = 200
DEFAULT_DEADLINE_SECONDS = 30.0
HOOK_DEADLINE_SECONDS = 10.0
HOOK_STDIN_BYTES = 1_000_000

# ---------------------------------------------------------------------------------------------
# cue tables (matched on the casefolded sentence)
# ---------------------------------------------------------------------------------------------
_NEG_FOLLOW_DONT = (r"(?! (?:worry|bother|mind|know|think|understand|see|get|care|need|have|like|want|mean|recall|"
                    r"really|forget to mention|lo|bận tâm))")
_STRONG_RULE = [
    ("always", re.compile(r"(?<!\w)always(?!\w)")),
    ("never", re.compile(r"(?<!\w)never(?!\w)(?! (?:mind|said|does|did|was|were|had|been|seen|heard|have|has|saw|told|asked|"
                         r"before|really))")),
    ("dont", re.compile(r"(?<!\w)(?:do not|don't|don’t|dont)(?!\w)" + _NEG_FOLLOW_DONT)),
    ("from_now_on", re.compile(r"(?<!\w)(?:from now on|from here on|going forward|henceforth)(?!\w)")),
    ("remember_to", re.compile(r"(?<!\w)(?:remember to|don't forget to|don’t forget to)(?!\w)")),
    ("stop_doing", re.compile(r"(?<!\w)stop [a-z]+ing(?!\w)")),
    ("you_must", re.compile(r"(?<!\w)(?:you (?:must|should|need to|have to)|must (?:always|never|not|use|include|add)|"
                            r"should (?:always|never|not))(?!\w)")),
    ("please_do", re.compile(r"(?<!\w)please (?:always|never|don't|don’t|do not|make sure)(?!\w)")),
    # Vietnamese
    ("luon", re.compile(r"(?<!\w)luôn(?!\w)")),
    ("dung", re.compile(r"(?<!\w)đừng(?!\w)(?! (?:lo|bận tâm|ngại|buồn|sợ|hỏi))")),
    ("khong_duoc", re.compile(r"(?<!\w)không được(?!\w)(?! rồi)(?= \w)")),
    ("khong_dung", re.compile(r"(?<!\w)không dùng(?!\w)(?! được)")),
    ("tu_gio", re.compile(r"(?<!\w)(?:từ giờ|từ nay|từ bây giờ|kể từ giờ)(?!\w)")),
    ("bat_buoc", re.compile(r"(?<!\w)(?:bắt buộc|tuyệt đối không|cấm)(?!\w)")),
    ("nho", re.compile(r"(?:^|[,:;] |hãy |cần |phải )nhớ(?!\w)")),
]
_WEAK_RULE = [
    ("make_sure", re.compile(r"(?<!\w)make sure(?!\w)")),
    ("instead_of", re.compile(r"(?<!\w)instead of(?!\w)")),
    ("must", re.compile(r"(?<!\w)must(?!\w)(?! be\b)")),
    ("should", re.compile(r"(?<!\w)should(?!\w)")),
    ("avoid", re.compile(r"(?<!\w)(?:avoid|prefer)(?!\w)")),
    ("thay_vi", re.compile(r"(?<!\w)thay vì(?!\w)")),
    ("phai", re.compile(r"(?<!\w)phải(?!\w)(?! (?:rồi|thế|vậy|không))")),
    ("nen", re.compile(r"(?<!\w)nên(?!\w)")),
]
#: A weak cue only counts together with a durable marker (otherwise it is a one-off task: "make sure the tests pass").
_DURABLE = re.compile(
    r"(?<!\w)(?:every|each|whenever|all|any time|by default|this (?:repo|repository|project|codebase)|in this (?:repo|project)|"
    r"before (?:commit\w*|push\w*|merg\w*|releas\w*|deploy\w*|you commit)|after (?:every|each)|"
    r"mọi|mỗi|khi|trước khi|sau khi|trong (?:repo|dự án)|mặc định)(?!\w)")
_DECISION = re.compile(
    r"(?<!\w)(?:we(?: have|'ve|’ve)? decided|decided to|we(?: will|'ll|’ll) use|we(?:'re| are|’re) going with|we (?:chose|picked)|"
    r"let's go with|let’s go with|decision:|chốt|quyết định(?=\s*[:,]|\s+(?:là|dùng|giữ|chọn|sẽ))|"
    r"(?:đã|chúng ta|mình|team)\s+quyết định|(?:chúng ta|mình|team)(?: sẽ| đã)? (?:dùng|chọn)|đã thống nhất)(?!\w)")
_GOTCHA_ATTENTION = re.compile(
    r"(?<!\w)(?:careful|heads up|watch out|beware|gotcha|pitfall|caveat|note that|chú ý|cẩn thận|lưu ý|coi chừng)(?!\w)")
_GOTCHA_FAILURE = re.compile(
    r"(?<!\w)(?:(?:fails?|breaks?|crash(?:es)?|errors?) (?:when|if|unless)|(?<!bị )lỗi khi)(?!\w)")

_FIRST_PERSON_EN = re.compile(r"(?<!\w)(?:i|i'll|i’ll|i'm|i’m|i've|i’ve|i'd|i’d|ill)(?!\w)")
_FIRST_PERSON_VI = re.compile(r"(?<!\w)(?:mình|tôi|em|tui)(?!\w)")
_QUESTION_START = re.compile(
    r"^(?:(?:can|could|would|will|should|shall|do|does|did|is|are|was|were)(?! not\b)|why|what|how|when|where|who|which|any chance|"
    r"bạn có|có nên|tại sao|làm sao|sao|liệu|có phải)\b")
_HYPOTHETICAL_START = re.compile(r"^(?:if|imagine|suppose|what if|assuming|unless|nếu|giả sử|giả dụ|tưởng tượng)\b")
_ASSISTANT_START = re.compile(r"^(?:sure|certainly|of course|absolutely|i'll|i’ll|i will|i can|let me|here's|here’s|here is|"
                              r"got it|understood|dạ|vâng ạ)\b")
_REPORTED = re.compile(r"(?<!\w)(?:says?|said|according to|theo|docs? mention\w*)(?!\w)")
_LEADING_FILLER = re.compile(
    r"^(?:thanks|thank you|thx|ok|okay|great|sure|also|btw|by the way|one more thing|and|so|please|hi|hey|yes|yeah|well|now|"
    r"cảm ơn|cám ơn|ừ|vâng|nhé|à|thêm nữa|ngoài ra|còn nữa)\b[,:!. -]*", re.IGNORECASE)

_PERSONAL = re.compile(
    r"(?<!\w)(?:me|my|myself|answer|reply|respond|speak|talk|tone|emoji|verbose|concise|brief|greet|"
    r"tôi|mình|xưng hô|trả lời|giọng|ngắn gọn|dài dòng)(?!\w)")
_PROJECT = re.compile(
    r"(?<!\w)(?:repo|repository|codebase|project|team|everyone|we|our|contributors?|ci|commits?|committing|pull request|pr|"
    r"main|release\w*|changelog|pyproject|module|package|api|tests?|testing|pytest|build|deploy\w*|lint\w*|format\w*|"
    r"migration\w*|docs?|documentation|vendor|public|branch|dependenc\w+|version|files?|"
    r"dự án|nhóm|mọi người|tài liệu|phiên bản|thư viện|hàm|service|git)(?!\w)")

_CODEISH_LINE = re.compile(
    r"^(?:\s{4,}|\t|\$ |>>> |\.\.\. |def |class |import |from \S+ import |return\b|for .+ in .+:|while .+:|else:|try:|except\b|"
    r"traceback|file \"|  file |npm err|npm warn|error:|warning:|fatal:|(?:error|warn|warning|info|debug|critical|fail|failed|"
    r"passed|assertionerror|exception)\b[:\s]|\d{4}-\d{2}-\d{2}|\[\d{2}:\d{2}|\d{2}:\d{2}:\d{2}|[#/]{1,2} |<[a-z/!?]|\{|\}|@\w+\(|"
    r"[a-z_.]+\(.*\)\s*[;:{]?$|[|+\-]{3,}|\w+\.\w+:\d+|at \S+ \(.*\))", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_TAG_BLOCK = re.compile(r"<(system-reminder|command-[a-z-]+|local-command-[a-z]+|user-prompt-submit-hook|ide_[a-z_]+|"
                        r"task-notification|bash-[a-z]+)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ABBREV = re.compile(r"\b(e\.g|i\.e|etc|vs|approx|cf|no)\.(?=\s)", re.IGNORECASE)
_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_STOP = frozenset("a an the to of in on for and or but with that this it is are be as at by we you i our your my please "
                  "then so also just every each when whenever before after from into".split())
_NAME_OK = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Message:
    text: str
    session: str
    line: int
    strict: bool = False  # commit messages: only sentences that START with the cue


@dataclass(frozen=True)
class Candidate:
    text: str  # canonical proposal text
    memory_type: str  # rule | gotcha | decision
    scope: str  # shared | private
    name: str
    cue: str
    quote: str  # the sentence as the user wrote it (clipped)
    session: str = ""
    line: int = 0

    @property
    def ref(self) -> str:
        return f"{self.session}#L{self.line}"

    def key(self) -> str:
        digest = hashlib.sha256(self.text.casefold().encode("utf-8")).hexdigest()[:12]
        return f"{self.session}#{self.line}#{digest}"

    def as_dict(self) -> dict:
        return {"memory_type": self.memory_type, "scope": self.scope, "name": self.name, "cue": self.cue,
                "text": self.text, "evidence": [self.ref, self.quote]}


# ---------------------------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _canonical(sentence: str) -> str:
    body = sentence.strip().rstrip(" .!;:,…").strip()
    if not body:
        return ""
    return body[0].upper() + body[1:] + "."


def derive_name(text: str) -> str:
    """A stable, ref-safe name from the normalized text: up to 6 content words plus a short hash of the full text."""
    folded = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    ascii_text = "".join(ch for ch in folded if not unicodedata.combining(ch))
    words = [w for w in _NAME_OK.split(ascii_text) if w and w not in _STOP]
    key = _NAME_OK.sub(" ", ascii_text).split()
    digest = hashlib.sha256(" ".join(key).encode("utf-8")).hexdigest()[:6]
    slug = "-".join(words[:6])[:48].strip("-")
    return f"{slug}-{digest}" if slug else f"item-{digest}"


def _clean_blocks(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TAG_BLOCK.sub(" ", text)
    return _FENCE.sub(" ", text)


def _sentences(text: str) -> Iterator[str]:
    for raw in _clean_blocks(text).split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if _CODEISH_LINE.match(line) or line.lstrip().startswith((">", "|", "#", "//", "--")):
            continue
        stripped = line.strip()
        stripped = re.sub(r"^(?:[-*•]\s+|\d+[.)]\s+)", "", stripped)  # list bullets are still the user's sentences
        protected = _ABBREV.sub(lambda m: m.group(0).replace(".", "\x00"), stripped)
        for part in _SPLIT.split(protected):
            part = part.replace("\x00", ".").strip()
            if part:
                yield part


def _classify_sentence(sentence: str, strict: bool = False) -> Optional[tuple]:
    """``(memory_type, cue)`` for an instruction-like sentence, else ``None``. ``strict`` (commit messages, which are mostly
    indicative prose such as "days are always written whole") needs the cue in the first two words and no weak cues."""
    s = _norm(sentence)
    # leading filler: "Also, don't ..." / "One more thing: you must ..."
    for _ in range(3):
        stripped = _LEADING_FILLER.sub("", s, count=1)
        if stripped == s:
            break
        s = stripped
    low = s.casefold()
    if len(s) < MIN_CHARS or len(s) > MAX_CHARS or len(s.split()) < MIN_WORDS:
        return None
    if low.endswith("?") or _QUESTION_START.match(low) or _HYPOTHETICAL_START.match(low) or _ASSISTANT_START.match(low):
        return None
    if _REPORTED.search(low):
        return None
    symbols = sum(ch in "{}[]<>=;$\\|`" for ch in s)
    if symbols / max(1, len(s)) > 0.12:
        return None
    m = _DECISION.search(low)
    if m:
        return "decision", "decision"
    m = _GOTCHA_ATTENTION.search(low)
    if m:
        return "gotcha", "attention"
    durable = bool(_DURABLE.search(low))
    if _GOTCHA_FAILURE.search(low) and durable and not strict:
        return "gotcha", "failure"
    for cue, pattern in _STRONG_RULE:
        m = pattern.search(low)
        if m is None:
            continue
        before = low[max(0, m.start() - 24):m.start()].split()[-4:]
        if strict and len(low[:m.start()].split()) > 1:
            continue
        if _FIRST_PERSON_EN.search(" ".join(before)) or _FIRST_PERSON_VI.search(" ".join(before)):
            continue  # "I never said", "I'll make sure", "mình không dùng": the user talking about themselves
        return "rule", cue
    if durable and not strict:
        for cue, pattern in _WEAK_RULE:
            m = pattern.search(low)
            if m is None:
                continue
            before = low[max(0, m.start() - 24):m.start()].split()[-4:]
            if _FIRST_PERSON_EN.search(" ".join(before)):
                continue
            return "rule", cue
    return None


def _scope(sentence: str) -> str:
    low = sentence.casefold()
    if _PERSONAL.search(low):
        return "private"
    return "shared" if _PROJECT.search(low) else "private"


def _prepared(sentence: str) -> str:
    s = _norm(sentence)
    for _ in range(3):
        stripped = _LEADING_FILLER.sub("", s, count=1)
        if stripped == s:
            break
        s = stripped
    return s


def _secret_free(text: str) -> bool:
    from src.redaction.prescan import scan_text

    try:
        return bool(scan_text(text).safe)
    except Exception:  # noqa: BLE001 - fail closed
        return False


def extract_text(text: str, *, deny: Iterable = (), session: str = "", line: int = 0, strict: bool = False) -> list:
    """Candidates (in order, de-duplicated within the text) found in one USER-authored text."""
    out: list = []
    seen: set = set()
    patterns = list(deny)
    if not isinstance(text, str) or len(text) > MAX_PROCESS_CHARS:
        return out
    for sentence in _sentences(text[:MAX_MESSAGE_CHARS]):
        verdict = _classify_sentence(sentence, strict)
        if verdict is None:
            continue
        memory_type, cue = verdict
        prepared = _prepared(sentence)
        if not _secret_free(sentence) or not _secret_free(prepared):
            continue
        if any(p.search(prepared[:16384]) for p in patterns):
            continue
        canon = _canonical(prepared)
        if not canon:
            continue
        name = derive_name(canon)
        if name in seen:
            continue
        seen.add(name)
        quote = prepared if len(prepared) <= EVIDENCE_QUOTE_CHARS else prepared[: EVIDENCE_QUOTE_CHARS - 1].rstrip() + "…"
        if len(out) >= MAX_PER_MESSAGE:
            break
        out.append(Candidate(text=canon, memory_type=memory_type, scope=_scope(prepared), name=name, cue=cue,
                             quote=quote, session=session, line=line))
    return out


# ---------------------------------------------------------------------------------------------
# input parsing (every parser yields user-authored messages only)
# ---------------------------------------------------------------------------------------------
_SESSION_OK = re.compile(r"[^A-Za-z0-9._-]+")


def _session_id(value: Any, fallback: str) -> str:
    text = _SESSION_OK.sub("-", value).strip("-")[:48] if isinstance(value, str) else ""
    return text or fallback


def _text_of(content: Any) -> str:
    """Text of a message ``content``: a string or the ``text`` parts of a list. tool_result / tool_use / images are NOT text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n".join(parts)
    return ""


def _iter_lines(path: Path) -> Iterator[tuple]:
    with open(path, "rb") as handle:
        for number, raw in enumerate(handle, 1):
            if len(raw) > MAX_LINE_BYTES:
                continue
            yield number, raw.decode("utf-8", errors="replace").strip()


def iter_transcript(path: Path, *, session: Optional[str] = None) -> Iterator[Message]:
    default = _session_id(session, _session_id(Path(path).stem, "transcript"))
    for number, line in _iter_lines(Path(path)):
        if not line or '"user"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "user":
            continue
        if record.get("isMeta") or record.get("isSidechain") or record.get("isCompactSummary"):
            continue
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _TAG_BLOCK.sub(" ", _text_of(message.get("content"))).strip()
        if text:
            yield Message(text, session or _session_id(record.get("sessionId"), default), number)


def parse_transcript(path: Path, *, session: Optional[str] = None) -> list:
    return list(iter_transcript(path, session=session))


def parse_chat_jsonl(path: Path, *, session: Optional[str] = None) -> list:
    """Generic ``{"role", "content"}`` messages, one per line or as one JSON array."""
    path = Path(path)
    sid = session or _session_id(path.stem, "chat")
    out: list = []
    raw = path.read_bytes().decode("utf-8", errors="replace").strip()
    records: list = []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            records = [(i, r) for i, r in enumerate(data, 1)] if isinstance(data, list) else []
        except ValueError:
            records = []
    else:
        for number, line in _iter_lines(path):
            if line.startswith("{"):
                try:
                    records.append((number, json.loads(line)))
                except ValueError:
                    continue
    for number, record in records:
        if not isinstance(record, dict):
            continue
        role = record.get("role")
        content = record.get("content")
        if record.get("isSidechain") or record.get("isMeta") or "type" in record:
            continue  # Claude Code records belong to iter_transcript (sub-agent prompts are written by an agent, not the user)
        if role not in ("user", "human"):
            continue
        text = _text_of(content).strip()
        if text:
            out.append(Message(text, sid, number))
    return out


_TURN = re.compile(r"^(user|human|you|me|nguoi dung|người dùng)\s*:\s*(.*)$", re.IGNORECASE)
_OTHER_TURN = re.compile(r"^(assistant|ai|claude|bot|system|tool|agent|codex|hermes|model)\s*:\s*", re.IGNORECASE)


def parse_plain_text(text: str, *, session: str = "text") -> list:
    """``User: ...`` / ``Assistant: ...`` logs. Continuation lines belong to the turn they follow; text before any
    ``User:`` marker and everything under an assistant turn is ignored."""
    sid = _session_id(session, "text")
    out: list = []
    current: Optional[list] = None  # [start_line, [lines]] of a user turn
    for number, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        m = _TURN.match(raw.strip())
        if m:
            if current:
                out.append(Message("\n".join(current[1]).strip(), sid, current[0]))
            current = [number, [m.group(2)]]
        elif _OTHER_TURN.match(raw.strip()):
            if current:
                out.append(Message("\n".join(current[1]).strip(), sid, current[0]))
            current = None
        elif current is not None:
            current[1].append(raw)
    if current:
        out.append(Message("\n".join(current[1]).strip(), sid, current[0]))
    return [m for m in out if m.text]


def load_messages(path: Path, *, session: Optional[str] = None) -> list:
    """Auto-detect: Claude Code transcript JSONL, generic chat JSONL / JSON array, or a plain-text log."""
    path = Path(path)
    head = path.read_bytes()[:65536].decode("utf-8", errors="replace").lstrip()
    if head.startswith("[") or head.startswith("{"):
        claude = parse_transcript(path, session=session)
        if claude:
            return claude
        return parse_chat_jsonl(path, session=session)
    return parse_plain_text(path.read_bytes().decode("utf-8", errors="replace"),
                            session=session or _session_id(path.stem, "text"))


_AGENT_COMMIT = re.compile(r"co-authored-by:\s*(?:claude|codex|copilot|gemini|cursor|aider)|generated with|claude\.ai/code|"
                           r"\[bot\]|🤖", re.IGNORECASE)


def _unwrap(body: str) -> str:
    """Undo hard wrapping in a commit body: lines of one paragraph are joined; bullets stay separate."""
    lines: list = []
    for raw in body.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            lines.append("")
        elif lines and lines[-1] and not re.match(r"^(?:[-*•]|\d+[.)])\s", line) and not lines[-1].endswith((":",)):
            lines[-1] += " " + line
        else:
            lines.append(line)
    return "\n".join(lines).strip()


class MessageList(list):
    """A list of messages that also counts what was skipped (``skipped_agent``: commits written by an agent)."""

    skipped_agent = 0


def git_messages(repo: Path, *, since: Optional[str] = None, limit: int = MAX_GIT_COMMITS) -> list:
    """Commit messages as user statements. Commits that an agent wrote or co-authored are skipped."""
    from . import devlog_git as dg

    repo = Path(repo)
    dg.check_repo(repo)
    if since is not None:
        dg.check_ref(repo, since)
    try:
        dg._git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    except dg.GitLogError:
        return []
    args = ["log", "--no-merges", f"--max-count={int(limit)}", "--format=%x1e%h%x1f%B"]
    if since is not None:
        args.append(f"{since}..HEAD")
    out = MessageList()
    for record in dg._git(repo, *args).split("\x1e"):
        if not record.strip():
            continue
        sha, _sep, body = record.partition("\x1f")
        sha = sha.strip()
        if not sha:
            continue
        if _AGENT_COMMIT.search(body):
            out.skipped_agent += 1
            continue
        out.append(Message(_unwrap(body), _session_id(sha, "commit"), 1, strict=True))
    return out


# ---------------------------------------------------------------------------------------------
# state (idempotency)
# ---------------------------------------------------------------------------------------------
def _state_path(layout, profile: str) -> Path:
    return layout.data_root / f"learner-state-{_session_id(profile, 'profile')}.json"


def _load_state(path: Path) -> list:
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
        keys = data.get("processed") if isinstance(data, dict) else None
        return [k for k in keys if isinstance(k, str)] if isinstance(keys, list) else []
    except (OSError, ValueError):
        return []


STATE_LOCK_TIMEOUT = 10.0


def _save_state(path: Path, keys: list) -> None:
    """Merge ``keys`` into the state file: the whole load-merge-replace runs under a cross-process lock (bounded wait;
    ``OSError`` when it cannot be taken, which ``learn`` reports as ``state_error``)."""
    from src.corpus._fsretry import retry_transient
    from src.storage.coordination import locked

    try:
        with locked(path.with_name(path.name + ".lock"), mode="exclusive", timeout=STATE_LOCK_TIMEOUT):
            merged = _load_state(path)
            known = set(merged)
            for key in keys:
                if key not in known:
                    merged.append(key)
                    known.add(key)
            merged = merged[-MAX_STATE_KEYS:]
            tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
            tmp.write_bytes(json.dumps({"version": 1, "processed": merged}, separators=(",", ":")).encode("utf-8"))
            retry_transient(lambda: os.replace(tmp, path))
    except OSError:
        raise
    except Exception as exc:  # noqa: BLE001 - lock timeout types derive from the coordination layer
        raise OSError(f"learner state lock: {type(exc).__name__}") from None


# ---------------------------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------------------------
_PERMANENT = {"rejected_secret", "invalid"}
#: Refusals that say "not now": stop the run and leave the candidates unprocessed so a later run retries them.
_RETRY_LATER = {"daily_limit", "learning_off", "kill_switch", "settings_invalid", "agent_proposals_disallowed",
                "proposal_log_too_large"}


def _disabled_reason(cfg: ls.Settings) -> Optional[str]:
    if not cfg.valid:
        return "settings_invalid"
    if cfg.kill_switch:
        return "kill_switch"
    if cfg.effective_mode == "off":
        return "learning_off"
    return None


def learn(memory, messages: Iterable, *, project: Optional[str] = None, max_new: int = DEFAULT_MAX_PER_RUN,
          dry_run: bool = False, source_label: str = "text", deadline: float = DEFAULT_DEADLINE_SECONDS,
          settings_path: Optional[Path] = None) -> dict:
    """Extract from ``messages`` and submit proposals as ``memory``'s profile. Returns a report dict (never raises on
    refusals; a refused run says why in ``disabled`` / ``stopped``)."""
    max_new = max(1, min(int(max_new), HARD_MAX_PER_RUN))
    cfg = ls.load_settings(settings_path) if settings_path else ls.load_settings()
    report: dict = {"source": source_label, "skipped_agent_commits": getattr(messages, "skipped_agent", 0), "dry_run": bool(dry_run), "created": 0, "merged": 0, "rejected": {},
                    "skipped_processed": 0, "messages": 0, "candidates": [], "project": project,
                    "profile": memory.profile_id, "disabled": None, "stopped": None}
    why = _disabled_reason(cfg)
    if why:
        report["disabled"] = why
        return report
    deny = ls.compile_deny_patterns(cfg)
    state_file = _state_path(memory.layout, memory.profile_id)
    processed = set(_load_state(state_file))
    newly: list = []
    submitted = 0
    started = time.monotonic()
    try:
        for message in messages:
            if time.monotonic() - started > deadline:
                report["stopped"] = "deadline"
                break
            report["messages"] += 1
            for cand in extract_text(message.text, deny=deny, session=message.session, line=message.line,
                                    strict=message.strict):
                key = cand.key()
                if key in processed:
                    report["skipped_processed"] += 1
                    continue
                if submitted >= max_new:
                    report["stopped"] = "max"
                    break
                if dry_run:
                    report["candidates"].append(cand.as_dict())
                    submitted += 1
                    continue
                ref = f"{project}:{cand.ref}" if project else cand.ref
                result = memory.propose(cand.text, cand.memory_type, name=cand.name, scope=cand.scope,
                                        evidence=[ref[:EVIDENCE_QUOTE_CHARS], cand.quote], source="learner")
                if result.status == "proposed":
                    report["created"] += 1
                elif result.status == "merged":
                    report["merged"] += 1
                else:
                    reason = result.reason or result.status
                    report["rejected"][reason] = report["rejected"].get(reason, 0) + 1
                    if reason in _RETRY_LATER:
                        report["stopped"] = reason
                        break
                    if result.status in _PERMANENT or reason == "deny_pattern":
                        newly.append(key)
                    continue
                submitted += 1
                newly.append(key)
                report["candidates"].append(cand.as_dict())
            if report["stopped"]:
                break
    finally:
        if newly and not dry_run:
            try:
                _save_state(state_file, newly)
            except OSError:
                report["state_error"] = True
    return report


def hook_project(cwd: Any) -> Optional[str]:
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    name = re.split(r"[\\/]+", cwd.strip().rstrip("\\/"))[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")[:64]
    return name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name or "") else None


__all__ = ["Candidate", "Message", "derive_name", "extract_text", "git_messages", "hook_project", "iter_transcript", "learn",
           "load_messages", "parse_chat_jsonl", "parse_plain_text", "parse_transcript"]
