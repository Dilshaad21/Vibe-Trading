---
name: sync-fork-upstream
description: Use when you need to sync a forked repository with upstream changes, resolve merge conflicts intelligently, and push the result back to the fork's remote.
---

# Sync Fork with Upstream

## Overview

Fetch upstream changes, assess divergence complexity, merge or ask clarifying questions when tricky, then commit and push to the fork's remote.

## Step-by-step workflow

### 1. Ensure upstream remote exists
```bash
git remote -v
# If no 'upstream' remote:
git remote add upstream https://github.com/HKUDS/Vibe-Trading.git
```
Upstream repo: **https://github.com/HKUDS/Vibe-Trading**
Fork remote (origin): `git@github.com:Dilshaad21/Vibe-Trading.git`

### 2. Fetch upstream & inspect divergence
```bash
git fetch upstream
git log HEAD..upstream/main --oneline   # commits we're behind
git log upstream/main..HEAD --oneline   # commits only in fork (local work)
git diff --stat HEAD upstream/main      # files changed
```

### 3. Assess complexity — decide merge strategy

| Situation | Action |
|-----------|--------|
| Fork is behind, **no local commits** | Fast-forward: `git merge --ff-only upstream/main` |
| Fork has local commits, **no overlapping files** | Merge: `git merge upstream/main -m "chore: sync upstream"` |
| Both sides touched the **same files** | Rebase or cherry-pick — **stop and ask** (see §4) |
| Upstream has **breaking changes** (renamed modules, removed APIs) | **Stop and ask** before touching anything |

### 4. When to stop and ask (tricky cases)

Stop and present the user with:
- **What changed upstream** (summary of commits + affected files)
- **What conflicts exist** (`git merge --no-commit upstream/main` to preview, then `git merge --abort`)
- **Your recommended strategy with reasoning**
- **A question** confirming they want to proceed

Example prompt to user:
> "Upstream added 3 commits touching `agent/src/agent/loop.py` and `agent/api_server.py`.
> Our fork also modified `loop.py` in commit `abc1234`.
> Recommended: rebase our 2 local commits on top of upstream to keep a clean history.
> Conflict in `loop.py` lines 45–67 — I'll need to manually resolve.
> Shall I proceed with rebase, or do you prefer a merge commit?"

### 5. Execute the merge / rebase
```bash
# Simple merge
git merge upstream/main -m "chore: sync upstream $(date +%Y-%m-%d)"

# Rebase (cleaner history, preferred when fork has few local commits)
git rebase upstream/main
```

For conflicts during rebase:
```bash
git status                    # see conflicted files
# Edit files to resolve
git add <resolved-file>
git rebase --continue
```

If rebase goes wrong: `git rebase --abort` and fall back to merge.

### 6. Verify before pushing
```bash
git log --oneline -10         # confirm history looks correct
git diff upstream/main        # should be empty (or only local additions)
pytest --ignore=agent/tests/e2e_backtest --tb=short -q   # run tests if Python project
```

### 7. Commit (if merge commit) and push
```bash
# Merge already creates a commit; for rebase no extra commit needed
git push origin main
# If rebase rewrote history and remote has diverged:
# Ask user before force-pushing — explain the implications first
```

## When NOT to force-push

Never force-push to `main` without explicit user confirmation. Explain:
> "Force-pushing will rewrite history on the remote. Anyone else working off this branch will need to re-clone or hard-reset. Confirm?"

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Forgetting `git fetch` before comparing | Always fetch first; local `upstream/main` is stale otherwise |
| Merging without reading what changed | Run `git log` and `git diff --stat` first |
| Force-pushing without warning | Always confirm with user |
| Resolving conflicts blindly | Read both sides; ask user if intent is unclear |
