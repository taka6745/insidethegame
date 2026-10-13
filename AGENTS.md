# Working in InsideTheGame

This repo holds the hackathon project, its research and competitor data. Application code will live here as it develops.

- Follow the current task. Research does not choose a product or stack; implement decisions when requested.
- Keep code small, readable and reusable. Follow existing conventions; add structure only when it serves actual code.
- Preserve local changes. Keep credentials in ignored local files or approved secrets; never print or commit them.
- Test changed behaviour and check the actual output. Report what is verified and what remains uncertain.
- Keep READMEs brief: plain language, compact tables and graphics that show relationships, quantities or change.
- Cite primary sources for research. Distinguish observations, stated goals and hypotheses; date technology releases precisely.
- Business cases need evidence of a problem and a clear benefit to the League or its fans. Do not assume partner efficiency increases League value.
- Label synthetic and real data clearly. Preserve collected files, provenance and licence information; do not execute competitor code during audits.

## Current tooling

- [Research](research/README.md): business context, official requirements and technology sources. Recheck rules before submission.
- [Competitors](competitors/README.md): exported projects, repository metrics and collected samples.
- The root README is hand-edited except its marked competitor snapshot. `.github/scripts/build_report.py` updates that block and generates `competitors/README.md`; edit those templates and regenerate. Research graphics come from `.github/scripts/build_research.py`.
- Validate reports: `python3 .github/scripts/verify_report.py`.
- Test automation: `python3 -m unittest discover -s .github/scripts -p 'test_*.py'`.

Keep application-specific run and test commands here as code is added. The current automation layout does not prescribe the application's structure.
