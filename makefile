# Every target here is a command, not a file it builds. Without this, make compares the
# target's name against the tree and skips any target that finds a match: `mutants` was a
# silent no-op for as long as the mutmut cache directory existed, and `test`, `crap` and
# `check` gate CI, where a target that does nothing and succeeds is the worst answer
# available. Add new targets to this list.
.PHONY: local static.clean test crap lint lint.templates types check \
	hooks hooks.run mutants mutants.results mutants.browse mutants.check format \
	docker.build docker.run docker.latest release release.notes

# A manifest left in the source tree names whatever some earlier build digested, so every
# page goes on quoting those names and an edited stylesheet is served as it was. Cleared
# rather than rebuilt, because the app reads it once when it is created.
local: static.clean
	uv run main.py

static.clean:
	python3 spindrift/static_manifest.py --clear

test:
	uv run pytest tests --cov --cov-branch --cov-report=lcov:lcov.info

crap: test
	uv run crap4py spindrift --lcov lcov.info --max-crap 10

lint:
	uv run ruff check .
	uv run ruff format --check .

lint.templates:
	npx prettier --check spindrift/templates

types:
	uv run ty check --error-on-warning

check: lint lint.templates types test crap

hooks:
	uv run prek install

hooks.run:
	uv run prek run --all-files

# Mutation testing: change the source in ways the suite ought to notice, and report the
# changes it slept through. Not part of `check`, because a cold sweep is a minute and a half;
# afterwards only mutants in changed code are re-run, which is seconds. `mutants.results` names
# the survivors and `mutants.browse` is the same results in a terminal UI. There is no target
# for applying one: `uv run mutmut apply <mutant>` takes the name of the mutant to put into the
# working tree, which is a poor fit for a target that takes no arguments.
mutants:
	uv run mutmut run

mutants.results:
	uv run mutmut results

mutants.browse:
	uv run mutmut browse

# What the nightly workflow runs. `mutmut run` names the survivors but exits 0 whether there
# are any or not, so the count has to be read back out: `export-cicd-stats` writes the tally
# mutmut already holds to mutants/mutmut-cicd-stats.json. Only survivors fail. A timeout or a
# suspicious verdict says more about how loaded the runner was than about the tests.
#
# Worth running on Linux, which is where the nightly runs it. A mutant that changes nothing
# but the case of a filename survives on a case-insensitive filesystem — macOS by default —
# because the filesystem resolves `SETTINGS.HTML` back to the template that exists. Locally
# those are noise; on ext4 they are kills.
mutants.check: mutants
	uv run mutmut export-cicd-stats
	@survived=$$(python3 -c "import json; print(json.load(open('mutants/mutmut-cicd-stats.json'))['survived'])"); \
		test "$$survived" = 0 || { echo "$$survived mutant(s) survived; 'make mutants.results' names them"; exit 1; }

# Both, because `check --fix` and `format` each undo wrapping the other chose.
format:
	uv run ruff check --fix .
	uv run ruff format .
	npx prettier --write spindrift/templates

docker.build:
	docker build -t spindrift:local .

docker.run:
	docker run --rm --name spindrift -p 127.0.0.1:8000:8000 -v "${PWD}:/data" spindrift:local

docker.latest:
	docker run --rm --name spindrift --platform linux/amd64 -p 127.0.0.1:8000:8000 -v "${PWD}:/data" ghcr.io/theselftaughtdev42/spindrift:latest

release:
	@test -n "$(VERSION)" || { echo "VERSION is required, e.g. make release VERSION=0.2.0"; exit 1; }
	@git diff --quiet && git diff --cached --quiet || { echo "working tree is dirty; commit or stash first"; exit 1; }
	@test "$$(git rev-parse --abbrev-ref HEAD)" = main || { echo "not on main; switch first"; exit 1; }
	@git fetch --quiet origin main
	@test "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" || { echo "main and origin/main have diverged; reconcile before releasing"; exit 1; }
	@! git rev-parse -q --verify v$(VERSION) >/dev/null || { echo "tag v$(VERSION) already exists; delete it or pick another version"; exit 1; }
	git switch -c release/v$(VERSION)
	uv version $(VERSION)
	git add pyproject.toml uv.lock
	git commit -m "release $(VERSION)"
	git push -u origin HEAD
	gh pr create --fill --label internal
# GitHub works out mergeability in the background and reports UNKNOWN until it has, so wait
# for a verdict rather than a fixed number of seconds. The bound stops a hang.
	@n=0; while [ "$$(gh pr view release/v$(VERSION) --json mergeable -q .mergeable)" = UNKNOWN ] && [ $$n -lt 30 ]; do n=$$((n+1)); sleep 1; done
	git switch main
	gh pr merge release/v$(VERSION) --merge --delete-branch
	git pull --ff-only
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin v$(VERSION)
	gh release create v$(VERSION) --generate-notes --verify-tag

release.notes:
	@test -n "$(VERSION)" || { echo "VERSION is required, e.g. make release.notes VERSION=0.5.0"; exit 1; }
	@gh api repos/$$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/generate-notes \
		-f tag_name=v$(VERSION) -f target_commitish=main \
		--jq '"# " + .name + "\n\n" + .body'
