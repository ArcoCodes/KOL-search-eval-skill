# Skill Update Protocol

This skill does **not** check GitHub for updates automatically. Only run update
checks when the user explicitly asks for `check update`, `检查更新`, `更新 skill`,
or equivalent wording.

## Goals

- Keep normal KOL workflows fast and offline-friendly.
- Avoid changing a user's installed skill without explicit intent.
- Make version checks deterministic by comparing a version file, not arbitrary code.

## Version Source

Recommended repository layout:

```text
<skill-root>/
  SKILL.md
  VERSION
  references/update.md
  scripts/
```

`VERSION` should contain a single SemVer-like string:

```text
0.1.0
```

Every release that should notify users must bump `VERSION`. If code changes but
`VERSION` does not change, `check update` should report no update.

## Check Update Flow

When the user asks to check updates:

1. Read local `VERSION` from the installed skill directory.
2. Fetch the remote `VERSION` from GitHub raw content.
3. Compare exact strings after trimming whitespace.
4. Report one of:
   - `up to date`
   - `update available`
   - `cannot check update`

Do not prompt to update unless the user asked for update or the user responds
affirmatively after seeing an available version.

Network failures, missing remote files, private repo auth failures, or malformed
version strings should not block normal skill use. Report the issue briefly.

## Update Flow

When the user explicitly asks to update:

1. Check remote version first.
2. If local and remote versions match, say it is already up to date.
3. If an update is available, ask for confirmation before modifying files.
4. Backup the current installed skill directory.
5. Download the GitHub skill directory at the selected ref.
6. Replace the installed skill directory with the downloaded version.
7. Tell the user the update will be available on the next turn.

Never silently overwrite local changes. If local files appear modified or the
skill directory is a git worktree with uncommitted changes, stop and ask before
continuing.

## Suggested Commands

Use the existing skill installer for a fresh install only. It aborts if the
destination already exists, so update requires a backup-and-replace workflow.

Example check:

```bash
LOCAL_VERSION="$(tr -d '[:space:]' < "$CLAUDE_SKILL_DIR/VERSION")"
curl -fsSL "https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path-to-skill>/VERSION"
```

Example reinstall target:

```bash
python3 /Users/l13/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo <owner>/<repo> \
  --path <path-to-skill> \
  --ref <ref> \
  --dest <temporary-destination>
```

Then backup and replace the installed skill directory only after user
confirmation.

## Recommended UX

For `check update`, answer concisely:

```text
Current: 0.1.0
Latest: 0.1.1
Update available. Say "update this skill" when you want me to install it.
```

For `update`, answer after completion:

```text
Updated from 0.1.0 to 0.1.1. The new version will be available on your next turn.
Backup: <backup path>
```

## Non-Goals

- No automatic check on every skill invocation.
- No background update.
- No update without user confirmation.
- No update detection from commit SHA alone unless the repo intentionally uses
  SHA-based versions.
