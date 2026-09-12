# Snapshots carry their own major.minor format version

A snapshot declares its shape as `"spindrift": "major.minor"`, a number separate from both the
release version and the database's `user_version`. Import refuses a snapshot whose major
differs from the app's and accepts any minor. Snapshots outlive the build that wrote them,
sitting on disk until they are needed, so the rule for which ones still import has to be
settled before the first one is written. The release is the wrong number to key on, because
most releases don't change what a snapshot holds. The schema is also wrong, because a
migration that only rearranges storage leaves the snapshot's shape exactly as it was.

## Consequences

- Within a major, changes are additive only. Every field added in a minor has a default so
  older snapshots still parse, and unknown fields are ignored so newer snapshots still
  parse. Removing, renaming or redefining a field, or making one required, means a new
  major.
- There is no code to upgrade snapshots from older majors. Once a major bump happens, older
  snapshots are refused, until that particular bump is judged worth an upgrade step.
- There is no patch level. A change to the format is either compatible (minor) or it isn't
  (major).
