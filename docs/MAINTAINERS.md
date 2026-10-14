# Maintainers: publishing and releasing

Every command is commented. Replace the placeholders in angle brackets:

| Placeholder | Meaning | Example |
|---|---|---|
| `<handle>` | The GitHub account that will own the repository | `dzalf` |
| `<Your Name>` | The name stored in your commits (becomes public) | `Daniel Melendrez` |
| `<noreply-email>` | Your private GitHub commit address: GitHub → Settings → Emails → "Keep my email address private" shows it | `12345678+dzalf@users.noreply.github.com` |

The repository name used throughout the documentation is **`aixun-t3x-safe-flasher`**. If you publish
under another account or name, replace `dzalf/aixun-t3x-safe-flasher` in README.md, INSTALLATION.md,
CONTRIBUTING.md, docs/WORKFLOW.md, docs/SCRIPTS_GUIDE.md and pyproject.toml before step 3.

---

## 1. What is published, and what never is

The repository is the content of the workspace's `project/` folder: code, tests, docs, `tools/aixun.sh`,
`constraints/`. Everything else in the workspace stays on your machine:

| Workspace part | Published? | Why |
|---|---|---|
| `project/` | **Yes** (only the files git tracks) | Everything needed to rebuild the rest: `setup` or `pip install -e .` |
| `venv/` | No | Machine-specific (absolute paths, CPU architecture, Python version), ~280 MB; rebuilt by setup. Exact versions: `constraints/tested.txt` |
| `firmware/` | No | AiXun's files, not ours to redistribute; `./aixun online get` fetches them |
| `results/` | No | Logs, reports and `history.jsonl` contain the station's USB serial number |
| `config/`, `deliveries/` | No | Personal settings; old zip deliveries |

Private backup of your full workspace (firmware and results included), kept off GitHub:

```bash
cd ~/Documents/Scripts/aixun
tar --exclude='./venv' -czf ~/aixun-workspace-backup-$(date +%Y%m%d).tgz .
# everything except venv/ (it's rebuilt anyway); keep this archive private
```

---

## 2. First publication: a new repository with one clean commit

The new repository starts with a single commit, "Initial release 0.1.0". The development history (one
commit per delivery) stays in your local workspace; its content is documented in `docs/devlog/` and
`docs/DEVELOPMENT_REPORT.md`, which are published.

### Step 1: check the workspace

```bash
cd ~/Documents/Scripts/aixun
# the workspace root (the folder containing ./aixun and project/)

./aixun status
# must show branch 'main', no uncommitted changes, venv "matches pyproject.toml"

./aixun test
# expected: 104 passed (with JC_M_T3B_1.16.bin and JC_M_T3BS_1.16.bin in firmware/)
```

### Step 2: create the empty repository on GitHub

On <https://github.com/new>:

| Field | Value |
|---|---|
| Owner / Repository name | `<handle>` / `aixun-t3x-safe-flasher` |
| Description | `Safe Linux firmware updater, read-only probe and GUI for AiXun T3x soldering stations` |
| Visibility | Public |
| Add a README / .gitignore / license | **Leave all unticked** (the project has its own; anything added here would conflict with the first push) |

Then click **Create repository**. (Command-line alternative in step 5.)

### Step 3: export a clean copy of the project

```bash
EXPORT="$HOME/aixun-t3x-safe-flasher"
# a NEW folder outside the workspace, used only to make the first commit

mkdir "$EXPORT"
# fails if it already exists: pick another name or delete the old one first

git -C ~/Documents/Scripts/aixun/project archive HEAD | tar -x -C "$EXPORT"
# copies exactly the files git tracks at the current commit. Nothing ignored (firmware,
# logs, caches, venv, settings) can come along, and no history is copied.

cd "$EXPORT" && ls
# README.md, INSTALLATION.md, CONTRIBUTING.md, LICENSE, src/, tests/, tools/, docs/ …
```

### Step 4: make the first commit

```bash
git init -b main
# a brand-new repository whose first branch is called 'main'

git config user.name "<Your Name>"
git config user.email "<noreply-email>"
# who the commit says made it; stored in THIS repository only. This name and address become
# public with the commit; the noreply address keeps your real e-mail private.

git add -A
git commit -m "Initial release 0.1.0"
# one commit containing the whole project

python3 tools/check_publish.py .
# scans the commit for firmware, logs, history files, real USB serial numbers, keys and tokens,
# and lists the author(s) that will be public. Must end with "OK".
```

### Step 5: authenticate and push

```bash
sudo apt install -y gh
# GitHub's official command-line tool (package 'gh' on Kali/Debian/Ubuntu); skip if installed

gh auth login
# GitHub.com → HTTPS → "Yes" (authenticate Git with your GitHub credentials)
# → "Login with a web browser": open the page it shows and type the one-time code.
# The login is stored in ~/.config/gh (your account's credential; not in any repository)

git remote add origin https://github.com/<handle>/aixun-t3x-safe-flasher.git
# 'origin' = the repository created in step 2

git push -u origin main
# uploads the commit; '-u' remembers origin/main for later pushes
```

If you skipped step 2, this single command creates the repository and pushes in one go (instead of
the last two commands):

```bash
gh repo create aixun-t3x-safe-flasher --public --source . --remote origin --push \
  --description "Safe Linux firmware updater, read-only probe and GUI for AiXun T3x soldering stations"
```

### Step 6: first release

```bash
git tag -a v0.1.0 -m "0.1.0: package, GUI and workspace; hardware-validated on a T3BS"
git push origin v0.1.0
# an annotated version tag, uploaded

gh release create v0.1.0 --title "0.1.0" --notes-file CHANGELOG.md
# the release page on GitHub (you can trim the notes to the 0.1.0 section on the website)
```

### Step 7: on github.com

| Where | What |
|---|---|
| Actions tab | The `tests` workflow runs on the push. Check it's green; if not, open the log |
| Repository page → gear icon next to "About" | Topics: `aixun`, `soldering-station`, `firmware-updater`, `raspberry-pi`, `pyside6`, `linux` |
| Settings → General → Features | Issues are on by default for new repositories; Discussions optional |

### Step 8: point your workspace at the published repository

From now on, develop on the published history so that your pushes fit on top of it:

```bash
cd ~/Documents/Scripts/aixun

mv project project-dev-history
# keep the old repository (full development history) as a private archive; it's never pushed

git clone https://github.com/<handle>/aixun-t3x-safe-flasher.git project
# the published repository becomes the workspace's project/

git -C project config user.name "<Your Name>"
git -C project config user.email "<noreply-email>"
# same identity as in step 4, for future commits

./aixun reinstall && ./aixun test
# venv/ now runs the clone; everything should pass as before

rm -rf "$EXPORT"
# optional: the export folder has done its job
```

`firmware/`, `results/`, `config/` and `venv/` are untouched by this.

---

## 3. Everyday maintenance

```bash
cd ~/Documents/Scripts/aixun
git -C project switch -c feature/x        # work on a branch
./aixun test && ./aixun check-publish     # before every push
git -C project push -u origin feature/x   # then open a pull request and merge it on GitHub
git -C project switch main && git -C project pull   # bring the merged result back
```

Reviewing someone's pull request locally:

```bash
git -C project fetch origin pull/<number>/head:pr-<number>
git -C project switch pr-<number>
./aixun test
# ask for a hardware report whenever wire bytes or timing change
```

## 4. Releasing a new version

1. Update `version` in `pyproject.toml` and `__version__` in `src/t3x/__init__.py`.
2. Add a section to `CHANGELOG.md`; update `docs/DEVELOPMENT_REPORT.md` (status, test counts, hardware log).
3. `./aixun reinstall && ./aixun test && ./aixun check-publish`
4. Commit and push; then `git -C project tag -a vX.Y.Z -m "…"`, `git -C project push origin vX.Y.Z`,
   and `gh release create vX.Y.Z` (run inside `project/`).
