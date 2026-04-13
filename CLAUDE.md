# Symbol Memory Instructions For Claude

When this Python project uses `@symbol(...)`, treat `symbol_memory` as the primary navigation layer.

## Rules

- Run `symbol-memory build` or `symbol-memory validate` before relying on indexed data.
- Use `symbol-memory find`, `symbol-memory relations`, `symbol-memory show`, and `symbol-memory open` before broad grep.
- Treat `.symbol_memory/` as generated output, not hand-edited source.
- Respect the manual graph: relations come only from `r=[...]`.
- If a symbol is missing from the index, it is outside symbol-memory scope until annotated.
- Rebuild after refactors that move, rename, add, or remove annotated symbols.

## Commands

```bash
symbol-memory build .
symbol-memory validate .
symbol-memory list --project-root .
symbol-memory find QUERY --project-root .
symbol-memory show ID --project-root .
symbol-memory relations ID --project-root .
symbol-memory open ID --project-root .
```

## Output Style

- Prefer exact symbol ids, file paths, and line ranges.
- Mention validation problems before using stale artifacts.
- Do not infer structure or hidden relations that symbol memory does not expose.
