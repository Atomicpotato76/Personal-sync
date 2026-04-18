# Architecture Overview

Hermes coordinates a staged workflow:

1. Intake and plan generation
2. Human approval for the plan
3. Workstream execution
4. Structured review and selective retries
5. Local test execution
6. Human approval for merge
7. Artifact packaging

State lives in SQLite for resumability, while plan files, generated workspaces, test logs, and package bundles live on disk.
