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

# Cut a release. Bumps pyproject to $(VERSION), commits that, tags it `v$(VERSION)`, and
# pushes both — and the tag push is what the publish workflow builds the `$(VERSION)` and
# `major.minor` images from. So this one command is the whole release, and rolling back
# later is pinning one of the tags it produced. Run it on a clean `main`:
#
#   make release VERSION=0.2.0
#
# Keeping pyproject in step with the tag is the point of bumping it here: the tag is the
# source of truth, and this stops the file drifting into a version no build was ever cut at.
#
# The last step publishes the GitHub release, whose notes are the merged PRs since the last
# release, categorised by `.github/release.yml`. Preview them with `make release.notes`
# before cutting anything. `--verify-tag` is what stops a tag push that did not land from
# quietly cutting a release from main under the same name.
release:
	@test -n "$(VERSION)" || { echo "VERSION is required, e.g. make release VERSION=0.2.0"; exit 1; }
	@git diff --quiet && git diff --cached --quiet || { echo "working tree is dirty; commit or stash first"; exit 1; }
	uv version $(VERSION)
	git add pyproject.toml uv.lock
	git commit -m "release $(VERSION)"
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin HEAD
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
