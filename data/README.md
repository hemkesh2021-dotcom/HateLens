# Local data

`python -m hatelens.train --download` places the pinned HateXplain corpus and its checksum manifest in `raw/`. The corpus includes hateful and offensive posts used for supervised research. It is not committed to Git.

The running application creates `hatelens.sqlite3` for submitted comments, predictions, moderation decisions, and reviewed feedback. This stays on the local machine and is ignored by Git. Back up or archive it before starting a fresh workspace. Set `HATELENS_DATABASE` to use a different database file.

The application never trains directly on pending or rejected feedback. See the root README for the explicit candidate-training workflow.
