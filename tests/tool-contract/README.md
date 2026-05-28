# Tool Contract Tests

Every tool adapter should have a cheap verification command.

At minimum, verify:

- `project.status` returns valid JSON.
- Success responses include `ok`, `tool`, `timestamp`, and `data`.
- Error responses include `ok`, `tool`, `timestamp`, and `error`.
- Write, admin, and destructive tools support dry-run or document why no write tools exist yet.
- Admin and destructive tools require explicit confirmation.
- Public-read outputs do not expose secrets, tokens, private paths, API keys, cookies, credentials, or sensitive local details.
- `project.tail_logs` treats `source` as a logical source name, not as an arbitrary local path.

Replace this README with project-specific tests once the adapter runtime is chosen.
