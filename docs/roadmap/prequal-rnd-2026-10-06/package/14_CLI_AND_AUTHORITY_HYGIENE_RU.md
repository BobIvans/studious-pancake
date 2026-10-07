# CLI + Authority Hygiene

## CLI
Replace `"run" in args` / `args.index("run")` routing with one parser-owned subcommand result. Add adversarial tests where `run` appears as:
- config filename;
- JSON/string value;
- trailing option value;
- unrelated command argument.

## Authority maps
Remove GitHub/open-PR metadata from runtime authority identity. Keep separate `development_queue.json` if useful.

## Open PR hygiene
30 open PR observed. Foundational examples #443/#440/#428/#411/#467 are 1500+ commits behind current main. They are research archives, not merge candidates.

Fresh exception: #565 is only 5 commits behind and 1 ahead at audit time; review/rebase separately.
