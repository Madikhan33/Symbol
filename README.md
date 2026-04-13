# Symbol Memory

Manual symbol memory for Python codebases.

`symbol_memory` gives LLM coding agents a small, explicit navigation layer over
real code. You annotate only the symbols that matter, run a build once, and
then query by numeric symbol id instead of forcing the agent to read entire
files or scan the whole repository repeatedly.

It is intentionally not a RAG system, not a graph database, not an IDE clone,
and not a semantic inference engine.

## Why It Exists

Most code-assistance workflows fail in one of two ways:

1. The agent reads too much code and burns context on irrelevant files.
2. The agent guesses relationships that were never made explicit.

`symbol_memory` takes the opposite approach:

- semantics are manual
- structure is extracted automatically
- build once, query fast
- navigation is id-based and exact

If a symbol is not annotated, it does not exist for this system.

## Core Model

You annotate top-level functions, classes, and class methods with a single
decorator:

```python
from symbol_memory import symbol


@symbol(
    7,
    r=[2, 4, 6],
    role="auth",
    summary="Validates access token",
    notes="Critical auth path",
    tags=["auth", "critical"],
)
def validate_token(token: str) -> bool:
    return token == "ok"
```

Manual fields:

- `id`: primary numeric symbol id
- `r`: manually declared relation ids
- `role`: short human-written role
- `summary`: short human-written summary
- `notes`, `tags`, `expose`, `entrypoint`: optional metadata

Automatic fields:

- `name`
- `qualified_name`
- `symbol_type`
- `file_path`
- `start_line`
- `end_line`
- `parent_class_name`
- `child_method_ids`

The decorator does not wrap the object and does not change runtime behavior.

## What Gets Generated

Running a build produces a `.symbol_memory/` directory inside the target
project:

```text
.symbol_memory/
  index.json
  relations.json
  validation_report.json
  project_map.md
  symbols/
    7.md
    11.md
    20.md
```

These artifacts are optimized for two consumers:

- humans and agents reading markdown cards
- tools doing fast lookups from JSON indexes

## Query Surface

The public facade is `SymbolMemory`:

```python
from symbol_memory import SymbolMemory

memory = SymbolMemory(project_root=".")
memory.build()

symbol = memory.get_symbol(7)
relations = memory.show_relations(7)
code_slice = memory.open_symbol(7)
```

Supported operations:

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

## CLI

```bash
symbol-memory build path/to/project
symbol-memory validate path/to/project
symbol-memory find 7 --project-root path/to/project
symbol-memory show 7 --project-root path/to/project
symbol-memory relations 7 --project-root path/to/project
symbol-memory open 7 --project-root path/to/project
symbol-memory list --project-root path/to/project
```

## Installation

From a built wheel:

```bash
uv add ./dist/symbol_memory-0.1.0-py3-none-any.whl
```

Directly from this repository:

```bash
uv add git+https://github.com/Madikhan33/Symbol.git
```

From a local checkout:

```bash
uv add /path/to/Symbol
```

## Build

Build distributables with:

```bash
uv build
```

This produces:

- `dist/symbol_memory-0.1.0.tar.gz`
- `dist/symbol_memory-0.1.0-py3-none-any.whl`

## Design Principles

- Never infer semantic meaning from code automatically.
- Never invent relations automatically.
- Never import or execute user project code during scanning.
- Keep the API tool-first and intentionally small.
- Prefer exact file/line navigation over broad repository context loading.

## Repository Layout

```text
src/
  symbol_memory/
dist/
pyproject.toml
README.md
```
