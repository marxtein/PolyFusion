# Deterministic report corpus

This directory contains the evidence used to replace VSC's online AI analysis
with the deterministic report engine.

- `scans/`: five full 8 x 8 POPCON responses.
- `payloads/`: 64 compact frontend-equivalent report payloads per configuration.
- `ai-reports/`: archived model reports plus request provenance.
- `deterministic-reports/`: outputs generated without network calls.
- `analysis/`: pattern analysis and full replay validation.
- `manifest.json`: case mapping, status, timing, and SHA-256 hashes.

Rebuild and verify with:

```bash
.venv/bin/python scripts/build_report_corpus.py --replace
.venv/bin/python scripts/generate_ai_report_corpus.py --workers 2
.venv/bin/python scripts/analyze_report_corpus.py
```

`--replace` refuses to delete archived AI reports. A destructive rebuild
requires the additional `--force-delete-reports` confirmation. AI generation
is resumable and guarded by an exclusive corpus lock. The public analysis UI
remains disabled while the offline AI comparison is incomplete.
