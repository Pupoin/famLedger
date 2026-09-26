"""The build's own version string.

Baked in at image build time by the Dockerfile (``ARG MOSAIC_BUILD_VERSION``,
fed from the git tag by .github/workflows/release.yml). A plain git checkout has
no such value and honestly reports "dev" rather than claiming a release number.

Surfaced at ``GET /api/health`` and recorded in every export manifest, so
"which version wrote this data?" and "did my upgrade actually take effect?" are
both answerable without guessing.
"""

import os

__version__ = os.getenv("FAMLEDGER_BUILD_VERSION", os.getenv("MOSAIC_BUILD_VERSION", "dev"))
