# Several memories on one machine, and `zero-mem link`

Keep separate memories (work, personal, one per client) and point each agent at exactly one. Every command below was run
against temp dirs; to try them safely, first set:

```
export ZERO_MEM_MEMORIES=/tmp/zm/memories.toml XDG_CONFIG_HOME=/tmp/zm/xc XDG_STATE_HOME=/tmp/zm/xs \
       XDG_CACHE_HOME=/tmp/zm/xk XDG_DATA_HOME=/tmp/zm/xd
unset ZERO_MEM_DATA_ROOT
```

## Concepts
- A memory is one data root. The registry `memories.toml` (config dir; override `ZERO_MEM_MEMORIES`) maps NAME to an absolute
  root. Names: `[a-z0-9][a-z0-9_-]{0,39}`. `default` is built in (the current `ZERO_MEM_DATA_ROOT` / XDG default), always
  exists, and cannot be created, renamed, removed or deleted.
- The file is a closed schema, written atomically under a lock; the previous valid version is kept as `memories.toml.bak`.
  A damaged file is never overwritten: mutating commands refuse and say so; fix it or `cp memories.toml.bak memories.toml`.
- A named memory keeps its own `config.json` inside its root (`ZERO_MEM_CONFIG_PATH`, set automatically).

## Commands
```
zero-mem memory create work --description "client work"     # or --path DIR
zero-mem memory list [--json]          # name, path, sources, agents, last write; * = current
zero-mem memory use work               # default for later commands (stored in the registry)
zero-mem memory path work
zero-mem memory rename work client-a   # data does not move; pinned agents keep working
zero-mem memory remove work            # unregisters only; data kept
zero-mem memory remove work --delete-data --yes   # deletes files (never `default`)
```
`create` refuses a non-empty directory that is not a zero-mem data root, symlinks (or paths under one), and any path equal
to, inside, or containing another memory's root (including `default`).
`memory use` reminds you that agents already running keep the memory they were started with.

## Selecting a memory
`--memory NAME` works on every command (put it before the command: `zero-mem --memory work search okapi`). Precedence, first
match wins: `ZERO_MEM_DATA_ROOT` in the environment > `--memory` > `ZERO_MEM_MEMORY` > `memory use` default > XDG default.
If `ZERO_MEM_DATA_ROOT` is set and `--memory` is given, a note says the env var won. With a damaged registry, commands that
need it fail closed (exit 2); `doctor`, `version` and `memory ...` still run. `doctor` and `memory-status` show the active
memory, where it came from and the registry health.

## Sharing between memories (and machines)
Every named memory has its own sharing identity, peers, grants and imports: `zero-mem share ... --memory NAME`. Two memories on one
machine can therefore share with each other over loopback like two machines; see the quick start in
[peer-sharing.md](peer-sharing.md#quick-start-for-two-machines). The control panel serves one memory (`zero-mem ui --memory NAME`) and
its Sharing page acts on that memory ([control-panel.md](control-panel.md#sharing)).

## Linking agents
```
zero-mem link claude-code --memory work [--profile P] [--enable-write] [--enable-propose] [--allow-root DIR]... [--print]
zero-mem link claude-code --memory work --apply --yes      # runs `claude mcp add ...`, shown first
zero-mem link --list                                       # agent profiles per memory
zero-mem link --remove claude-code --memory work           # revokes grants, keeps data
```
`link` registers the profile on that memory if missing (READ shared, private write; `--enable-write` does not grant shared
writes, use `agents grant-write`) and prints the registration for claude-code, codex, hermes or openclaw. The env pins
`ZERO_MEM_DATA_ROOT` (and `ZERO_MEM_CONFIG_PATH`) of the memory, so the server uses exactly that memory. Default server name:
`zero-mem-<memory>` (`zero-mem` for default). `--apply` is only for claude-code (the client flow verified with a model), needs
`--yes`, and zero-mem never writes a client's config files; for the others, run the printed command yourself.
Agents already running keep their old memory: restart them after relinking.

Exit codes: 0 ok, 2 usage/setup error, 5 not found.
