# Hermes Auto-Development Pipeline

CLI-first multi-agent delivery pipeline that separates planning, implementation, review, testing, and packaging.

## Commands

```bash
hermes-pipeline plan "build a todo CLI"
hermes-pipeline plan --request-file .\proposal.md
hermes-pipeline approve <run-id> --stage plan
hermes-pipeline approve <run-id> --stage checkpoint --comment-file .\next-direction.md
hermes-pipeline run <run-id>
hermes-pipeline status <run-id>
hermes-pipeline directions <run-id>
hermes-pipeline watch <run-id>
hermes-pipeline notify <run-id>
hermes-pipeline feedback <run-id> --comment-file .\next-direction.md
hermes-pipeline approve <run-id> --stage merge
hermes-pipeline run <run-id>
hermes-pipeline artifacts <run-id>
hermes-pipeline doctor
```

## Secret Handling

- Keep real API keys in OS-level environment variables, not in workspace files.
- `.env.example` is a template only.
- PowerShell example:

```powershell
setx ANTHROPIC_API_KEY "your-new-key"
setx OPENAI_API_KEY "your-new-key"
```

- Open a new terminal after `setx`, then run `hermes-pipeline doctor` to scan for accidental secret exposure.
- Optional Discord notifications can be enabled with `DISCORD_WEBHOOK_URL` and `DISCORD_WEBHOOK_USERNAME`.

## Discord Notifications

- If `DISCORD_WEBHOOK_URL` is set, Hermes sends plain-language updates to Discord when the plan is ready, a checkpoint is waiting, tests are waiting for merge approval, the run fails, and the package completes.
- You can also manually push the current summary with `hermes-pipeline notify <run-id>`.

## Layout

- `apps/cli`: user-facing Typer CLI
- `apps/gui`: local desktop GUI for plan, approval, run, and summary actions
- `contracts/`: shared Pydantic contracts
- `services/`: adapters, orchestration, persistence, testing
- `plans/`: saved plan bundles and markdown summaries
- `outputs/`: workspaces, execution logs, packages
- `tests/`: unit and integration coverage

## Proposal And Direction Files

- `hermes-pipeline plan "..."` still works for short requests.
- `hermes-pipeline plan --request-file .\proposal.md` lets you start from a markdown proposal file.
- `hermes-pipeline plan .\proposal.md` also works if the positional value points to an existing UTF-8 text file.
- If the proposal is long, Hermes automatically builds a shorter planning digest before sending it to the planner.
- `hermes-pipeline feedback <run-id> "..."` saves the next direction as plain text.
- `hermes-pipeline feedback <run-id> --comment-file .\next-direction.md` saves the next direction from a markdown file.
- `hermes-pipeline approve <run-id> --stage checkpoint --comment-file .\approval-notes.md` attaches file-based approval notes to the approval record.

## Artifact Storage

- Plans live under `plans/<run-id>/`.
- Current plan JSON: `plans/<run-id>/plan_bundle.json`
- Human-readable plan summary: `plans/<run-id>/summary.md`
- Plan history: `plans/<run-id>/versions/`
- Saved direction snapshots: `plans/<run-id>/directions/`
- Generated worktree: `outputs/<run-id>/workspace/`
- Execution reports: `outputs/<run-id>/executions/`
- Review reports: `outputs/<run-id>/reviews/`
- Test reports and logs: `outputs/<run-id>/tests/`
- Final package and manifest: `outputs/<run-id>/package/`

## Terminal View

- `hermes-pipeline status <run-id>` prints the latest checkpoint summary once.
- `hermes-pipeline directions <run-id>` prints the latest saved direction guidance.
- `hermes-pipeline watch <run-id>` keeps refreshing the summary in the same terminal window until you stop it with `Ctrl+C`.
- `python -m apps.cli.main plan --request-file .\proposal.md` also works directly from the project directory.

## Direction Guidance

- After each modification cycle pauses for review, final testing, failure handling, or completion, Hermes saves a direction snapshot under `plans/<run-id>/directions/`.
- `latest_direction.md` and `latest_direction.json` always point to the newest recommendation so you can reopen it quickly.
