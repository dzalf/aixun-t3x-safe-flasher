# Maintainers: pushing changes and making releases

For whoever has write access to `github.com/dzalf/aixun-t3x-safe-flasher`.

**Where to run the commands:** every command below runs in the **workspace folder**, the folder that
contains `./aixun` and `project/` (see [INSTALLATION.md](../INSTALLATION.md) §4). Open a terminal and go
there first by typing `cd` followed by the folder's path, for example:

```bash
cd ~/aixun
# replace ~/aixun with the path of YOUR workspace folder; ~ means your home folder
```

`git -C project …` means "run this git command inside the `project/` folder", so you never need to leave
the workspace folder.

---

## 1. What is published, and what never is

| Workspace part | Published? | Why |
|---|---|---|
| `project/` | **Yes** (only the files git tracks) | Code, tests, docs, `tools/aixun.sh`, `constraints/` |
| `venv/` | No | Specific to one machine (absolute paths, processor type, Python version), ~280 MB; `./aixun setup` rebuilds it |
| `firmware/` | No | AiXun's files, not ours to redistribute |
| `results/` | No | Logs, reports and `history.jsonl` contain the station's USB serial number |
| `config/`, `deliveries/` | No | Personal settings; applied zip snapshots |

`.gitignore` keeps these out, and `./aixun check-publish` checks for them before every push (section 4).

Private backup of the whole workspace (firmware and results included), kept off GitHub:

```bash
tar --exclude=./venv -czf ~/aixun-workspace-backup.tgz .
# run in the workspace folder: packs everything except venv/ (it's rebuilt anyway) into the file
# aixun-workspace-backup.tgz in your home folder. Keep it private: it contains firmware and logs.
```

---

## 2. GitHub access from the command line: a personal access token

`git push` needs proof that you are allowed to write to the repository. GitHub doesn't accept your account
password for this. You use a **personal access token** instead, a secret string made on the GitHub website.

### 2.1 What the token must allow

Make or edit it at github.com → your profile picture → **Settings** → **Developer settings** →
**Personal access tokens**. A token starting with `github_pat_` is "fine-grained"; one starting with
`ghp_` is "classic".

| Token type | Settings needed |
|---|---|
| Fine-grained (`github_pat_…`) | **Repository access:** includes `dzalf/aixun-t3x-safe-flasher` (a token limited to "selected repositories" does not cover repositories created after it). **Repository permissions:** **Contents** = Read and write, **Workflows** = Read and write |
| Classic (`ghp_…`) | Scopes **repo** and **workflow** ticked |

**Workflows** (or **workflow**) is needed because the repository contains `.github/workflows/tests.yml`.
Without it GitHub refuses any push that includes a change to that folder.

### 2.2 Using it

When `git push` asks for a username, type your GitHub username. When it asks for a password, paste the
token, not your account password. Nothing appears on screen while you paste; that's normal. Press Enter.

### 2.3 Error messages and what they mean

| Message | Meaning | Fix |
|---|---|---|
| `Invalid username or token` | Wrong or expired token, or the account password was typed | Paste the token again; make a new one if it expired |
| `Permission to … denied to …` with `403` | The token was accepted, but it may not write to this repository | Section 2.1: repository access and **Contents** |
| `refusing to allow a Personal Access Token to create or update workflow` | The token lacks the workflow permission | Section 2.1: **Workflows** / **workflow** |

### 2.4 Saving the token so git stops asking

```bash
git -C project config credential.helper store
# for this repository only: the next time you type your username and token, git saves them in the
# file .git-credentials in your home folder and stops asking
```

| | |
|---|---|
| Risk | The file is **not encrypted**. Anyone who can log in as your user, or who gets a copy of your home folder, can push with it. Limit the token to this one repository and give it an expiry date |
| Check | `ls -l ~/.git-credentials` must start with `-rw-------` (readable only by you). Never paste its contents anywhere |
| Token expired or replaced | The push fails and git removes the stored entry; the next push asks again and saves the new token |
| Undo | `git -C project config --unset credential.helper`, then `rm ~/.git-credentials` |

To keep it in memory for one hour instead of saving it in a file:
`git -C project config credential.helper "cache --timeout=3600"`.

---

## 3. Commit identity (once per clone)

Every commit records a name and an e-mail address, and both become public when pushed. To keep your real
address private, use GitHub's "noreply" address:

1. github.com → your profile picture → **Settings** → **Emails**.
2. Tick **Keep my email addresses private**. The page then shows your noreply address, of the form
   `<number>+<username>@users.noreply.github.com`. Copy it exactly.
3. Optional, same page: tick **Block command line pushes that expose my email**. GitHub then refuses any
   push whose commits carry your real address.

Set it for the repository:

```bash
git -C project config user.name "Your Name"
# replace Your Name with the name you want shown on your commits (keep the quotes)

git -C project config user.email "PASTE-THE-NOREPLY-ADDRESS"
# replace PASTE-THE-NOREPLY-ADDRESS with the address copied in step 2 (keep the quotes)

git -C project config user.email
# prints the address now in use: check it is the noreply one
```

These settings are stored in `project/.git/config`. That file is never uploaded.

---

## 4. Everyday: from a change to GitHub

### 4.1 A zip snapshot

A snapshot is a zip of the project folder (what it is and how to make one: [WORKFLOW.md](WORKFLOW.md) §3).
Put the zip in the workspace's `deliveries/` folder, then:

```bash
./aixun apply my_change.zip
# replace my_change.zip with the zip's file name. Puts it on a new branch and commits it
# with the message "Delivery: my_change"; updates venv/ if needed

./aixun test
# must pass

./aixun accept
# merges it into main (commit message "Accept my_change")

./aixun check-publish
# must end with "OK": no firmware, logs, serial numbers, keys or tokens. Also lists the commit
# authors, so you can see which e-mail addresses become public

git -C project push origin main
# uploads the new commits to GitHub
```

If the tests fail: `./aixun rollback` asks for confirmation (`y`), returns to `main` and deletes the
test branch.

### 4.2 Your own edits

```bash
git -C project add -A
# stages every change you made inside project/

git -C project commit -m "Fix typo in INSTALLATION.md"
# the message: one short line (under about 70 characters) saying what the change does,
# written as a command: "Add …", "Fix …", "Update …"

./aixun test
./aixun check-publish
git -C project push origin main
```

### 4.3 Someone else's pull request

On GitHub, a pull request has a number (for example **#12**). To test pull request 12 locally:

```bash
git -C project fetch origin pull/12/head:pr-12
# downloads its commits into a local branch called pr-12 (replace both 12s with the real number)

git -C project switch pr-12
# switches project/ to that branch

./aixun reinstall
./aixun test
# installs its dependencies (only if they changed) and runs the tests

git -C project switch main
# back to main when done; merge the pull request with the button on GitHub
```

Ask for a hardware report when the change affects what is sent to the station or its timing.

After merging on GitHub, bring the result to your machine:

```bash
git -C project pull
# downloads the merged changes into project/
```

---

## 5. Making a release

Example for version **0.2.0**. Replace `0.2.0` everywhere with the new version.

1. Edit the version in two files: `version = "0.2.0"` in `project/pyproject.toml`, and
   `__version__ = "0.2.0"` in `project/src/t3x/__init__.py`.
2. Rename the `## Unreleased` heading at the top of `project/CHANGELOG.md` to `## 0.2.0 — <date>`, and
   update `project/docs/DEVELOPMENT_REPORT.md` (status, test counts, hardware log).
3. Then:

```bash
./aixun reinstall
./aixun test
# installs the new version number into venv/ and checks everything passes

git -C project add -A
git -C project commit -m "Release 0.2.0"
# records the version change

./aixun check-publish
# must end with "OK"

git -C project push origin main
# uploads the commit

git -C project tag -a v0.2.0 -m "0.2.0"
git -C project push origin v0.2.0
# marks the commit as version 0.2.0 and uploads the tag
```

4. On github.com: repository page → **Releases** → **Draft a new release**. Choose tag `v0.2.0`, set the
   title to `0.2.0`, paste the 0.2.0 section of `CHANGELOG.md` as the description, then
   **Publish release**.
5. **Actions** tab: check that the `tests` run for the push is green.

---

## 6. How the repository was first published (0.1.0)

For reference only; this doesn't need repeating. The tracked files of the private development
repository were exported without history (`git archive`), committed once as "Initial release 0.1.0" in a
new repository, checked with `tools/check_publish.py`, pushed with a personal access token and tagged
`v0.1.0`. The development history stays private; its content is summarised in `docs/devlog/` and
`docs/DEVELOPMENT_REPORT.md`.
