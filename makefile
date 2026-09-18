# Clear the image build's leavings before starting, because a manifest sitting in the source
# tree is what the app reads to find its static files — and it names whatever some earlier
# build digested. Leave one there and every page goes on quoting those names, so an edited
# stylesheet is served as it was whenever that build ran. The failure reads as a change that
# did not take, which is a bad half-hour to hand anybody.
#
# Clearing rather than rebuilding: the manifest is read once when the app is created, so a
# fresh one would be stale again by the second edit of a session. With nothing there the app
# is in its ordinary development mode — plain names, served by Flask with `no-cache`.
#
# Stdlib only, on the system interpreter, exactly as the Dockerfile runs the same script.
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

# Cut a release. Bumps pyproject to $(VERSION) on a branch, merges that through a pull
# request, then tags the merged commit and pushes it — and the tag push is what the publish
# workflow builds the `$(VERSION)` and `major.minor` images from. So this one command is the
# whole release, and rolling back later is pinning one of the tags it produced. Run it on a
# clean `main`:
#
#   make release VERSION=0.2.0
#
# The pull request is not ceremony: the `Protect Main` ruleset requires one and grants no
# bypass to anybody, so pushing the release commit straight at main is rejected outright and
# the tag never leaves the machine. Nothing gates the PR once it is open — no approvals, no
# required checks — so it is created and merged back to back here.
#
# Keeping pyproject in step with the tag is the point of bumping it here: the tag is the
# source of truth, and this stops the file drifting into a version no build was ever cut at.
#
# The tag goes on the *merged* commit, not on the branch's. A merge commit is what main
# actually gets, so tagging before the merge would pin every image of this release to a
# commit that main never had.
#
# The release PR is labelled `internal`, which `.github/release.yml` excludes, so a release
# does not open its own notes by announcing itself. The last step publishes the GitHub
# release, whose notes are the merged PRs since the last release. Preview them with
# `make release.notes` before cutting anything. `--verify-tag` is what stops a tag push that
# did not land from quietly cutting a release from main under the same name.
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
# GitHub works out whether a PR can merge in the background, and reports UNKNOWN until it
# has. Merging into that answer fails for a reason that is not real, so wait for a verdict
# rather than for a fixed number of seconds. The bound is there so a repository that never
# settles stops the release instead of hanging on it.
	@n=0; while [ "$$(gh pr view release/v$(VERSION) --json mergeable -q .mergeable)" = UNKNOWN ] && [ $$n -lt 30 ]; do n=$$((n+1)); sleep 1; done
	git switch main
	gh pr merge release/v$(VERSION) --merge --delete-branch
	git pull --ff-only
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin v$(VERSION)
	gh release create v$(VERSION) --generate-notes --verify-tag

# What `make release` would publish as notes, without publishing anything. Creates no
# release and no tag — it asks the same API `--generate-notes` calls, so what prints here
# is what lands. Run it against the version you are about to cut:
#
#   make release.notes VERSION=0.5.0
#
# Empty output means no PRs merged since the last release: the work went straight to main
# and there is nothing for the generator to list.
release.notes:
	@test -n "$(VERSION)" || { echo "VERSION is required, e.g. make release.notes VERSION=0.5.0"; exit 1; }
	@gh api repos/$$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/generate-notes \
		-f tag_name=v$(VERSION) -f target_commitish=main \
		--jq '"# " + .name + "\n\n" + .body'
