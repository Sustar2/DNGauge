# GitHub Release Guide

## Goal

Only publish the final files inside `release/` as GitHub Release assets.

## Current behavior

Workflow file:

- `.github/workflows/build-packages.yml`

When you push a tag like `v0.1.0`, GitHub Actions will:

1. build Linux package
2. build Windows package
3. place final archives into `release/`
4. create a GitHub Release
5. upload the files found in `release/`

## Expected release files

Typical examples:

- `release/DNGauge-linux-portable.zip`
- `release/DNGauge-windows-portable.zip`

## How to publish

```bash
git checkout main
git pull
git tag -a v0.1.0 -m "DNGauge v0.1.0"
git push origin main --tags
```

## Important note

I can update the local workflow and repository structure here, but I cannot directly delete an already-published GitHub Release from the remote repository in this environment.

If you already published an old Release on GitHub, you need to delete it on GitHub itself, or use a tool like `gh` on your machine.
