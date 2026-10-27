# Design knowledge (vendored, unmodified)

The designer agent reads these files as data; their code is not used. Retrieval glue lives in
`app/knowledge/`.

| Folder | Source | Commit | License | Used for |
|---|---|---|---|---|
| `ui-ux-pro-max/` | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) `.claude/skills/ui-ux-pro-max` | `28b3b8dee8c976df4fa3e94aed4e092ad43fcb03` | MIT (`ui-ux-pro-max/LICENSE`) | Product profiles (style, palette, typography mood, effects, anti-patterns), font pairings, UX guidelines per platform, app-interface rules, chart choice, landing patterns, HTML/Tailwind rules, pre-delivery checklist |
| `frontend-design/` | [anthropics/skills](https://github.com/anthropics/skills) `skills/frontend-design` | `dbd4588f9e1033efb41dad4bef2f7947c8993d44` | Apache-2.0 (`frontend-design/LICENSE.txt`) | Aesthetic principles and copywriting guidance in the builder prompt |

Copied files (upstream `data/` is stored as `datasets/`, since `data/` is ignored by git/docker): `data/{products,ui-reasoning,colors,typography,styles,ux-guidelines,app-interface,charts,landing}.csv`,
`data/stacks/html-tailwind.csv`, `references/pro-rules.md`, `SKILL.md`.

Update: download the repository at a newer commit, copy the same files, update the commit above and run
`tests/test_knowledge.py`.
