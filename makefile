# Clear the image build's leavings first: a manifest left in the source tree names whatever
# some earlier build digested, so every page goes on quoting those names and an edited
# stylesheet is served as it was. Cleared rather than rebuilt, because the app reads the
# manifest once when it is created. Stdlib only, on the system interpreter, as the
# Dockerfile runs it.
local: static.clean
	uv run main.py

static.clean:
	python3 spindrift/static_manifest.py --clear

docker.build:
	docker build -t spindrift:local .

docker.run:
	docker run --rm --name spindrift -p 127.0.0.1:8000:8000 -v "${PWD}:/data" spindrift:local

docker.latest:
	docker run --rm --name spindrift --platform linux/amd64 -p 127.0.0.1:8000:8000 -v "${PWD}:/data" ghcr.io/theselftaughtdev42/spindrift:latest

# Cut a release: bump pyproject on a branch, merge it through a pull request, then tag the
# merged commit and push. The tag push is what the publish workflow builds the `$(VERSION)`
# and `major.minor` images from, so this one command is the whole release.
#
#   make release VERSION=0.2.0
#
# The pull request is not ceremony: the `Protect Main` ruleset requires one and grants no
# bypass, so pushing the release commit straight at main is rejected and the tag never leaves
# the machine. Nothing gates the PR once open, so it is created and merged back to back. The
# tag goes on the *merged* commit, which is what main actually gets. The PR is labelled
# `internal`, which `.github/release.yml` excludes, so a release does not announce itself in
# its own notes. `--verify-tag` stops a tag push that did not land from cutting a release
# from main under the same name.
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
# for a verdict rather than for a fixed number of seconds. The bound stops a repository that
# never settles from hanging the release.
	@n=0; while [ "$$(gh pr view release/v$(VERSION) --json mergeable -q .mergeable)" = UNKNOWN ] && [ $$n -lt 30 ]; do n=$$((n+1)); sleep 1; done
	git switch main
	gh pr merge release/v$(VERSION) --merge --delete-branch
	git pull --ff-only
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin v$(VERSION)
	gh release create v$(VERSION) --generate-notes --verify-tag

# What `make release` would publish as notes, without publishing anything: it asks the same
# API `--generate-notes` calls, so what prints here is what lands. Empty output means no PRs
# merged since the last release.
#
#   make release.notes VERSION=0.5.0
release.notes:
	@test -n "$(VERSION)" || { echo "VERSION is required, e.g. make release.notes VERSION=0.5.0"; exit 1; }
	@gh api repos/$$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/generate-notes \
		-f tag_name=v$(VERSION) -f target_commitish=main \
		--jq '"# " + .name + "\n\n" + .body'
