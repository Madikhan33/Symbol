---
name: symbol-memory
description: "Use when working in Python repositories that already use `@symbol(...)` and `.symbol_memory` artifacts. Build or validate first, navigate with symbol ids, and respect the manual relation graph."
---

# Symbol Memory

Use this skill when a Python project already uses `symbol_memory` annotations and generated artifacts.

## Rules

- Build or validate before trusting symbol memory data.
- Prefer `find`, `relations`, and `open` before broad repository grep.
- Treat `.symbol_memory/` as generated output unless the user explicitly asks to inspect artifacts.
- Do not invent relations. Links come only from manual `r=[...]`.
- If a symbol is not annotated, do not assume it exists in symbol memory.
- Rebuild after edits that move, add, remove, or renumber annotated symbols.

## Core Workflow

```bash
symbol-memory build .
symbol-memory validate .
symbol-memory list --project-root .
symbol-memory find QUERY --project-root .
symbol-memory show ID --project-root .
symbol-memory relations ID --project-root .
symbol-memory open ID --project-root .
```

## Response Behavior

- Prefer symbol ids, exact paths, and exact line ranges.
- Surface validation errors before relying on stale artifacts.
- Use raw text search only after symbol-memory navigation is exhausted.
