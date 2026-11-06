# Third-party components

Hegemone is licensed under GPL-3.0-only. Dependencies keep their own licenses;
Hegemone's license does not replace their copyright or attribution notices.

## Frontend

[FRONTEND_LICENSES.txt](FRONTEND_LICENSES.txt) contains the full license and
copyright notices for the bundled frontend JavaScript dependencies and Tailwind's
generated CSS. The production build regenerates the notices with
`rollup-plugin-license`; CI compares the output with this checked-in snapshot.
The deployed application serves the same text at `/third-party-licenses.txt`,
with a version/license inventory at `/third-party-packages.json`. Each generated
JavaScript chunk points to the notices. A new dependency or missing/unknown
license requires review before the build succeeds.

The current frontend includes MIT, ISC and BSD-2-Clause components. Icons come
from Lucide, distributed through `@lucide/svelte` under ISC. The application's
buoy mark is inline project SVG. No external font, image or icon files are
bundled separately.

`svelte-toolbelt@0.10.6` omits a license identifier in its package metadata, but
ships an MIT LICENSE including its copyright holders. The build recognizes only
that reviewed version and license text; other missing identifiers fail review.

Compiler/build packages are installed from the npm lockfile and are not copied
into the runtime container. In particular, is-reference, locate-character,
stackback, esbuild and Rollup's native build packages are not part of the bundled
frontend module inventory. Their installed package metadata remains available in
source-development environments.

## Python and container components

The runtime installs the pinned requirements from `uv.lock`, including the MCP
extra. Python packages retain their distribution metadata, LICENSE/COPYING and
NOTICE files under the installed `*.dist-info` directories. The container smoke
check verifies that installed distributions retain license files. The uv binary
is mounted only for the installation build step and is not copied into a final
image layer.

The final image derives from `python:3.12-slim-bookworm`. Python's license and the
base operating system's package copyright/license files remain in their upstream
locations, including the Python standard-library directory and
`/usr/share/doc/*/copyright`. The source/build stages use Node.js and uv; those
stages are not the distributed runtime image.

Do not remove these notices or dependency metadata when redistributing the
application or container. If dependencies or bundled assets change, rebuild,
review the new notices, update the snapshot and verify the final image again.
