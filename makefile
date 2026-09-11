local:
	uv run main.py

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
release:
	@test -n "$(VERSION)" || { echo "VERSION is required, e.g. make release VERSION=0.2.0"; exit 1; }
	@git diff --quiet && git diff --cached --quiet || { echo "working tree is dirty; commit or stash first"; exit 1; }
	uv version $(VERSION)
	git add pyproject.toml uv.lock
	git commit -m "release $(VERSION)"
	git tag -a v$(VERSION) -m "v$(VERSION)"
	git push origin HEAD
	git push origin v$(VERSION)