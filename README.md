<p align="center">
  <img src="https://raw.githubusercontent.com/Madikhan33/Symbol/main/assets/banner.svg" alt="Symbol Memory" width="100%">
</p>

# Symbol Memory

<p align="center">
  <strong>Manual symbol memory for Python codebases.</strong><br>
  Explicit symbol indexing for agents, tools, and developers who need exact navigation.
</p>

<p align="center">
  <a href="https://github.com/Madikhan33/Symbol"><img src="https://img.shields.io/badge/GitHub-Madikhan33%2FSymbol-111827?style=for-the-badge&logo=github" alt="GitHub"></a>
  <a href="https://pypi.org/project/symbol-memory/"><img src="https://img.shields.io/pypi/v/symbol-memory?style=for-the-badge&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://github.com/Madikhan33/Symbol/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Built%20with-uv-6C47FF?style=for-the-badge" alt="Built with uv">
  <img src="https://img.shields.io/badge/Validation-Structured-F59E0B?style=for-the-badge" alt="Structured validation">
</p>

**Symbol Memory** gives Python projects a small, explicit navigation layer on top of real source code.  
You annotate the symbols that matter, build once, and then query the project by exact symbol id instead of repeatedly scanning large files or guessing relationships.

It is intentionally **not** a RAG system, **not** a semantic search layer, and **not** a code execution engine.  
The model is simple: manual meaning, automatic structure, deterministic lookup.

```bash
uv add symbol-memory
```

```python
from symbol_memory import SymbolMemory, symbol
```

---

## Why This Exists

Most code-assistance pipelines fail in one of two ways:

1. They read too much code and waste context on irrelevant files.
2. They invent connections that were never explicitly defined.

Symbol Memory takes the opposite approach:

- semantics stay manual
- structure comes from AST
- relations remain explicit and auditable
- navigation stays exact and stable

If a symbol is not annotated, it does not exist for this system.

---

## At a Glance

<table>
<tr>
  <td><b>Exact symbol graph</b></td>
  <td>Map important functions, classes, and methods to string ids and manual relation ids.</td>
</tr>
<tr>
  <td><b>AST-only scanning</b></td>
  <td>Reads source without importing or executing project code.</td>
</tr>
<tr>
  <td><b>Fast generated artifacts</b></td>
  <td>Produces JSON indexes and markdown symbol cards optimized for repeat lookup.</td>
</tr>
<tr>
  <td><b>Validation-first workflow</b></td>
  <td>Reports duplicate ids, broken relations, malformed metadata, and artifact drift with structured diagnostics.</td>
</tr>
<tr>
  <td><b>CLI and Python API</b></td>
  <td>Use it from scripts, local tooling, or directly from the terminal.</td>
</tr>
</table>

---

## Core Model

Annotate top-level functions, classes, and class methods with a single decorator:

```python
from symbol_memory import symbol


@symbol(
    "1",
    r=["2", "1.2"],
    role="auth",
    summary="Validates access token",
    notes="Critical auth path",
    tags=["auth", "critical"],
)
def validate_token(token: str) -> bool:
    return token == "ok"
```

### Manual metadata

- `id`: primary string symbol id such as `"1"` or `"1.2"`
- `r`: manually declared relation ids
- `role`: short human-written role
- `summary`: short human-written summary
- `notes`: optional string or `None`
- `tags`: optional list of strings; omitted values normalize to `[]`
- `expose`: optional boolean
- `entrypoint`: optional boolean

### Validation rules

- symbol ids use numeric dot-separated string segments such as `"1"` or `"1.2.3"`
- `r` is required, but `r=[]` is completely valid
- `role` and `summary` must be non-empty string literals
- `tags` may be omitted, `None`, or a list of non-empty strings
- the decorator does not wrap the object and does not change runtime behavior

### Automatically extracted fields

- `name`
- `qualified_name`
- `symbol_type`
- `file_path`
- `module_path`
- `start_line`
- `end_line`
- `parent_class_name`
- `child_method_ids`
- `hierarchy_parent_id`
- `hierarchy_child_ids`

---

## Quick Start

### Install

```bash
uv add symbol-memory
```

The package name is `symbol-memory`, but the Python import is `symbol_memory`.

### Annotate symbols

```python
from symbol_memory import symbol


@symbol(
    "1",
    r=["2"],
    role="auth",
    summary="Validates access token",
)
def validate_token(token: str) -> bool:
    return token == "ok"
```

### Build symbol memory

```bash
symbol-memory build path/to/project
```

### Query it

```bash
symbol-memory list --project-root path/to/project
symbol-memory find auth --project-root path/to/project
symbol-memory show 1 --project-root path/to/project
symbol-memory relations 1 --project-root path/to/project
symbol-memory branches 1 --project-root path/to/project
symbol-memory children 1 --project-root path/to/project
symbol-memory parent 1.2 --project-root path/to/project
symbol-memory roots --project-root path/to/project
symbol-memory open 1 --project-root path/to/project
```

### Validate after changes

```bash
symbol-memory validate path/to/project
```

### End-to-end example

```bash
uv add symbol-memory
symbol-memory build path/to/project
symbol-memory show 1 --project-root path/to/project
symbol-memory relations 1 --project-root path/to/project
```

---

## Python API

```python
from symbol_memory import SymbolMemory

memory = SymbolMemory(project_root=".")

report = memory.build()
if report.status == "error":
    print(report.error_count)

symbol = memory.get_symbol("1")
relations = memory.show_relations("1")
branches = memory.list_branches("1")
source = memory.open_symbol("1")
```

Main API surface:

- `build()`
- `validate()`
- `find()`
- `get_symbol()`
- `get_symbol_card()`
- `show_relations()`
- `preview_relation()`
- `open_symbol()`
- `open_file_range()`
- `list_symbols()`
- `list_children()`
- `list_branches()`
- `get_parent()`
- `list_roots()`

---

## CLI Reference

| Command | Purpose |
|---|---|
| `symbol-memory build [project-root]` | Scan source and write `.symbol_memory/` |
| `symbol-memory validate [project-root]` | Compare source truth with saved artifacts |
| `symbol-memory find QUERY` | Lookup by id, exact name, qualified name, or substring |
| `symbol-memory show ID` | Print the markdown symbol card |
| `symbol-memory relations ID` | Show resolved relation previews |
| `symbol-memory branches ID` | Print the full branch tree rooted at the given id |
| `symbol-memory children ID` | Print direct children for the given id |
| `symbol-memory parent ID` | Print the direct parent for the given id |
| `symbol-memory roots` | Print all root-level symbols |
| `symbol-memory open ID` | Print the source slice for a symbol |
| `symbol-memory list` | List all indexed symbols sorted by id |

---

## Generated Artifacts

Running a build creates a `.symbol_memory/` directory inside the target project:

```text
.symbol_memory/
  index.json
  relations.json
  validation_report.json
  project_map.md
  symbols/
    1.md
    1.1.md
    2.md
```

<table>
<tr>
  <td><code>index.json</code></td>
  <td>Canonical machine-readable index with symbols and lookup tables.</td>
</tr>
<tr>
  <td><code>relations.json</code></td>
  <td>Resolved relation previews for each source symbol.</td>
</tr>
<tr>
  <td><code>validation_report.json</code></td>
  <td>Structured validation output with issue codes, locations, and hints.</td>
</tr>
<tr>
  <td><code>project_map.md</code></td>
  <td>High-level human-readable project overview.</td>
</tr>
<tr>
  <td><code>symbols/{id}.md</code></td>
  <td>Markdown card for each indexed symbol, including dotted ids such as <code>1.1.md</code>.</td>
</tr>
</table>

---

## Validation and Error Handling

Symbol Memory is built to fail clearly.

Diagnostics include:

- stage-aware issues from `scan`, `parse`, `resolve`, `artifact`, and `query`
- exact issue codes
- file and line context where available
- field-level hints for broken decorator metadata
- drift detection when generated artifacts no longer match source

Examples of problems it catches:

- duplicate symbol ids
- invalid decorator usage
- invalid literal types in metadata
- missing relation target ids
- missing or broken generated artifacts
- stale symbol cards or lookup indexes after refactors

`build` still writes `.symbol_memory/validation_report.json` even when errors exist, so broken states remain inspectable and debuggable.

---

## Agent Prompts

This repository includes project prompts in formats that are practical to use directly:

- Codex skill: [codex/skills/symbol-memory/SKILL.md](codex/skills/symbol-memory/SKILL.md)
- Claude project file: [CLAUDE.md](CLAUDE.md)

They are intentionally short. They tell the agent to:

- build or validate before relying on symbol memory
- use `find`, `relations`, and `open` before broad grep
- treat `.symbol_memory/` as generated output
- respect the manual relation model from `r=[...]`

### How to use them

- Codex:
  Copy the `codex/skills/symbol-memory/` folder into your Codex skills directory or install it as a local skill.
- Claude:
  Copy `CLAUDE.md` into the root of the target repository so Claude can pick it up as a project instruction file.

---

## Design Principles

- Never infer semantic meaning from code automatically.
- Never invent relations automatically.
- Never import or execute user project code during scanning.
- Keep the system small, explicit, and tool-first.
- Prefer exact source coordinates over fuzzy repository search.

---

## Current Scope

Supported in the current version:

- Python `3.12+`
- top-level functions
- top-level classes
- class methods
- string ids such as `"1"` and `"1.2"`
- hierarchy inferred from dotted ids
- `@symbol(...)`
- `@module.symbol(...)`

Not supported in v1:

- nested symbol indexing
- alias-aware decorator resolution
- multi-language scanning
- automatic relation discovery
- semantic inference
- incremental rebuilds

---

## Development

```bash
git clone https://github.com/Madikhan33/Symbol.git
cd Symbol
uv sync
uv run --with pytest pytest
uv build
```

---

## License

MIT - see [LICENSE](LICENSE).
