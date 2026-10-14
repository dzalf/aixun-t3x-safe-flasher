# Maintainers: pushing changes and making releases

Every command below is written out in full, with the folder it runs in. The paths are the
maintainer's own:

| What | Path |
|---|---|
| Workspace (contains `./aixun`, `project/`, `venv/`, `firmware/`, `results/`) | `/home/kali/Documents/Scripts/aixun` |
| The repository (a clone of `github.com/dzalf/aixun-t3x-safe-flasher`) | `/home/kali/Documents/Scripts/aixun/project` |

If your workspace is somewhere else, replace `/home/kali/Documents/Scripts/aixun` with your path. That
is the only thing to replace.

---

## 1. What is published, and what never is

| Workspace part | Published? | Why |
|---|---|---|
| `project/` | **Yes** (only the files git tracks) | Code, tests, docs, `tools/aixun.sh`, `constraints/` |
| `venv/` | No | Specific to one machine (absolute paths, processor type, Python version), ~280 MB; `./aixun setup` rebuilds it |
| `firmware/` | No | AiXun's files, not ours to redistribute |
| `results/` | No | Logs, reports and `history.jsonl` contain the station's USB serial number |
| `config/`, `deliveries/` | No | Personal settings; old zip deliveries |

`.gitignore` keeps these out, and `./aixun check-publish` checks for them before every push (section 4).

Private backup of the whole workspace (firmware and results included), kept off GitHub:

```bash
cd /home/kali/Documents/Scripts/aixun
# the workspace folder

tar --exclude=./venv -czf /home/kali/aixun-workspace-backup.tgz .
# packs everything except venv/ (it's rebuilt anyway) into /home/kali/aixun-workspace-backup.tgz.
# Keep this file private: it contains your firmware and logs.
```

---

## 2. GitHub access from the command line: a personal access token

`git push` needs proof that you are the account `dzalf`. GitHub doesn't accept the account password for
this. You use a **personal access token** instead, a secret string made on the GitHub website.

### 2.1 What the token must allow

Make or edit it at github.com → profile picture → **Settings** → **Developer settings** →
**Personal access tokens**. A token starting with `github_pat_` is "fine-grained"; one starting with
`ghp_` is "classic".

| Token type | Settings needed |
|---|---|
| Fine-grained (`github_pat_…`) | **Repository access:** includes `dzalf/aixun-t3x-safe-flasher` (a token limited to "selected repositories" does not cover repositories created after it). **Repository permissions:** **Contents** = Read and write, **Workflows** = Read and write |
| Classic (`ghp_…`) | Scopes **repo** and **workflow** ticked |

**Workflows** (or **workflow**) is needed because the repository contains `.github/workflows/tests.yml`.
Without it GitHub refuses any push that includes a change to that folder.

### 2.2 Using it

When `git push` asks:

```text
Username for 'https://github.com': dzalf
Password for 'https://dzalf@github.com': (paste the token here)
```

Nothing appears on screen while you paste. That's normal; press Enter.

### 2.3 Error messages and what they mean

| Message | Meaning | Fix |
|---|---|---|
| `Invalid username or token` | The token is wrong, expired, or you typed your account password | Paste the token again; make a new one if it expired |
| `Permission to dzalf/aixun-t3x-safe-flasher.git denied to dzalf` … `403` | The token was accepted, but it may not write to this repository | Section 2.1: repository access and **Contents** |
| `refusing to allow a Personal Access Token to create or update workflow` | The token lacks the workflow permission | Section 2.1: **Workflows** / **workflow** |

### 2.4 Optional: don't retype the token for an hour

```bash
git -C /home/kali/Documents/Scripts/aixun/project config credential.helper "cache --timeout=3600"
# for this repository only: after you paste the token once, git keeps it in memory (not on disk)
# for 3600 seconds = 1 hour
```

To stop it: `git -C /home/kali/Documents/Scripts/aixun/project config --unset credential.helper`

---

## 3. Commit identity (once)

Every commit records a name and an e-mail address, and both become public when pushed. To keep your real
address private, use GitHub's "noreply" address:

1. github.com → profile picture → **Settings** → **Emails**.
2. Tick **Keep my email addresses private**. The page then shows your noreply address, of the form
   `<number>+dzalf@users.noreply.github.com`. Copy it exactly.
3. Optional, same page: tick **Block command line pushes that expose my email**. GitHub then refuses any
   push whose commits carry your real address.

Set it for the repository:

```bash
git -C /home/kali/Documents/Scripts/aixun/project config user.name "Daniel Melendrez"
# the name shown on your commits

git -C /home/kali/Documents/Scripts/aixun/project config user.email "PASTE-THE-NOREPLY-ADDRESS"
# replace PASTE-THE-NOREPLY-ADDRESS with the address copied in step 2 (keep the quotes)

git -C /home/kali/Documents/Scripts/aixun/project config user.email
# prints the address now in use: check it is the noreply one
```

These settings live in this repository only (`project/.git/config`), not system-wide.

---

## 4. Everyday: from a change to GitHub

### 4.1 A zip delivery

```bash
cd /home/kali/Documents/Scripts/aixun
# the workspace folder; every ./aixun command runs here

./aixun apply t3x_sessionXX.zip
# replace t3x_sessionXX.zip with the delivery's file name. Puts it on a new branch
# delivery/t3x_sessionXX and updates venv/ if needed

./aixun test
# must pass

./aixun accept
# merges the delivery into main

./aixun check-publish
# must end with "OK": no firmware, logs, serial numbers, keys or tokens. Also lists the commit
# authors, so you can see which e-mail addresses become public

git -C /home/kali/Documents/Scripts/aixun/project push origin main
# uploads to GitHub (username dzalf, password = token)
```

If the tests fail: `./aixun rollback` asks for confirmation (`y`), returns to `main` and deletes the delivery branch.

### 4.2 Someone else's pull request

On GitHub, a pull request has a number (for example **#12**). To test pull request 12 locally:

```bash
git -C /home/kali/Documents/Scripts/aixun/project fetch origin pull/12/head:pr-12
# downloads its commits into a local branch called pr-12

git -C /home/kali/Documents/Scripts/aixun/project switch pr-12
# switches the project to that branch

cd /home/kali/Documents/Scripts/aixun
./aixun reinstall
./aixun test
# install its dependencies (only if they changed) and run the tests

git -C /home/kali/Documents/Scripts/aixun/project switch main
# back to main when done; merge the pull request with the button on GitHub
```

Ask for a hardware report when the change affects what is sent to the station or its timing.

After merging on GitHub, bring the result back to the Pi:

```bash
git -C /home/kali/Documents/Scripts/aixun/project pull
# downloads the merged changes into project/
```

---

## 5. Making a release

Example for version **0.2.0**. Replace `0.2.0` everywhere with the new version.

1. Edit the version in two files: `version = "0.2.0"` in
   `/home/kali/Documents/Scripts/aixun/project/pyproject.toml`, and `__version__ = "0.2.0"` in
   `/home/kali/Documents/Scripts/aixun/project/src/t3x/__init__.py`.
2. Add a `## 0.2.0 — <date>` section at the top of `CHANGELOG.md`, and update
   `docs/DEVELOPMENT_REPORT.md` (status, test counts, hardware log).
3. Then:

```bash
cd /home/kali/Documents/Scripts/aixun

./aixun reinstall
./aixun test
# the new version number is installed into venv/ and everything passes

git -C /home/kali/Documents/Scripts/aixun/project add -A
git -C /home/kali/Documents/Scripts/aixun/project commit -m "Release 0.2.0"
# records the version change

./aixun check-publish
# must end with "OK"

git -C /home/kali/Documents/Scripts/aixun/project push origin main
# uploads the commit

git -C /home/kali/Documents/Scripts/aixun/project tag -a v0.2.0 -m "0.2.0"
git -C /home/kali/Documents/Scripts/aixun/project push origin v0.2.0
# marks the commit as version 0.2.0 and uploads the tag
```

4. On github.com: repository page → **Releases** → **Draft a new release**. Choose tag `v0.2.0`, set the
   title to `0.2.0`, paste the 0.2.0 section of `CHANGELOG.md` as the description, then
   **Publish release**.
5. **Actions** tab: check that the `tests` run for the push is green.

---

## 6. Record: first publication (2026-10-14)

How the repository was created, for reference. It doesn't need repeating.

1. Empty repository `dzalf/aixun-t3x-safe-flasher` created on github.com (no README, .gitignore or
   licence added there).
2. The tracked files of the development repository were exported without history:
   `git -C /home/kali/Documents/Scripts/aixun/project archive HEAD | tar -x -C /home/kali/Documents/Scripts/aixun-export`
3. In `/home/kali/Documents/Scripts/aixun-export`: `git init -b main`, one commit
   "Initial release 0.1.0", `python3 tools/check_publish.py .` → OK.
4. Pushed with a personal access token (section 2): `git remote add origin https://github.com/dzalf/aixun-t3x-safe-flasher.git`,
   `git push -u origin main`. The first attempt failed with the two errors in section 2.3; fixed by
   giving the token access to the new repository and the workflow permission.
5. Tag `v0.1.0` pushed; release page made on the website.
6. In the workspace, the old development repository was renamed to `project-dev-history` (kept privately,
   never pushed), and the published repository was cloned as `project`.
