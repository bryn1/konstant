---
name: workspace-layout
description: Where every file goes in a konstant workspace - one directory per project under projects/, docs/ARCHITECTURE.md as the one architecture statement, each run's output in its OUT directory under .audits/, scratch under OUT/.tmp/, no sibling or persona-named directories, no secrets, supersede instead of overwrite. Load before creating any file or directory.
---
# Workspace layout

If a file's location cannot be predicted from its project and its kind, the next reader has to
search for it, and work that cannot be found is treated as not done.

## The layout

```
<workspace>/                       the konstant folder (konstant.toml, var/, catalog/, bin/)
  projects/<project>/              ONE directory per project, lowercase-kebab, its own git tree
    docs/ARCHITECTURE.md           the one architecture statement: modules, entry points, ports,
                                   dependencies, data stores; kept true by the architect
    docs/adr/                      decision records (skill `adr`)
    .audits/<YYYYMMDD-HHMMSS>-<slug>/out/
                                   OUT of one run: verdict files, DONE.md, CYCLES.md, findings,
                                   evidence/ (captured outputs cited in DONE.md)
    .audits/<...>/out/.tmp/        scratch for that run; never a deliverable
  var/runs/<stamp>-<slug>/         konstant's run record, phase manifests and logs (never edit)
```

A project added with an explicit path outside the workspace keeps the same inner layout.

## Rules

- `<project>` names the thing being built, never the agent or the task kind; check for an existing
  directory with another casing or a prefix before creating one (`ls projects/ | grep -i <name>`).
  A second directory for one project is the defect this layout prevents.
- One run, one fresh OUT directory, timestamped in UTC at the start of the run; never reuse an
  earlier run's directory, never write run output loose at the project root.
- Source files go into the project tree under its own conventions; architecture statements go into
  `docs/ARCHITECTURE.md`, never a second `DESIGN.md` beside it.
- `mkdir -p` the target directory before writing.
- An artifact cited by a tracked document must resolve from a fresh clone: commit it, or the
  document does not cite the path.
- Process artifacts (prompts, phase summaries, transcripts, one-off scripts) never enter the product
  repository; they live in the run directory or OUT.
- **Append, do not overwrite**: never delete or overwrite another agent's file; supersede your own
  earlier output with a new dated file in a fresh run directory.
- **No secrets** in any project or run directory: no tokens, keys, passwords or `.env` contents.
- Keep a report under about 150 lines; split a larger deliverable into parts inside its OUT.
