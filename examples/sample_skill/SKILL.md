---
name: repo-onboarding
description: Inspect an unfamiliar repository and summarize supported facts.
triggers:
  - inspect
  - repository
  - onboarding
  - summarize
inputs:
  - user task
  - file index preview
  - workspace tree
outputs:
  - repository summary
  - likely test command
  - relevant entrypoints
allowed_tools:
  - shell
forbidden_paths:
  - .git
  - .mini_claw
verification:
  - cite observed files or command output
---

# Repo Onboarding

Use this skill when entering an unfamiliar repository.

1. List top-level files.
2. Identify package manager and test command.
3. Read the shortest entrypoint first.
4. Summarize only facts supported by files or command output.
