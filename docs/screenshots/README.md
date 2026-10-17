# Screenshots

Captured from the running stack, not mocked. `frontend/scripts/screenshots.mjs`
starts the API on a throwaway SQLite database, serves the production frontend
build, imports real projects through the UI and photographs the result.

```bash
cd frontend
npm run screenshots
```

| File | What it shows |
| --- | --- |
| `01-landing-dark.png` | Import form — GitHub URL, ZIP upload, demo |
| `02-landing-light.png` | The same page in the light theme |
| `03-analysis-live.png` | Live progress, mid-run, importing a real repository |
| `04-analysis-complete.png` | The finished stepper with per-stage issue counts |
| `05-dashboard-dark.png` | Report: score, sub-scores, severity chart, issue table |
| `06-dashboard-light.png` | The same report in the light theme |
| `07-issue-drawer.png` | One finding: evidence, explanation, before/after fix |
| `08-coverage.png` | What was examined, and the caveats |
| `09-architecture-placeholder.png` | The Phase 6 placeholder tab |
| `10-dashboard-mobile.png` | The report at 390 px |

Two different projects appear, on purpose:

- The **live progress** shots import
  [`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template)
  — a real React + FastAPI repository, large enough (250 files, ~6 s end to
  end) that the stepper can be photographed while it is still running rather
  than already finished.
- The **dashboard** shots analyse the bundled demo fixture, whose defects are
  fixed and asserted by the test suite, so the picture is reproducible.

No Gemini key is configured during capture, which is why the report shows
`explained by AI: 0` and `from templates: 5`. That is the offline path, and
it is the one most people will see first.
