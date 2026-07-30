# Local generated artifacts

This is the only repository-local root for disposable development output.

- `tmp/`: pytest basetemp, temporary databases, generated helper scripts, extracted schemas, and other reproducible scratch files.
- `verification/`: local screenshots, command output, JSONL transcripts, and reports intentionally retained for short-term verification.

Everything below `.artifacts/` except this file is ignored by Git. Use a task-specific subdirectory and delete it when the task is complete. Do not place credentials or copies of real third-party session stores here.
