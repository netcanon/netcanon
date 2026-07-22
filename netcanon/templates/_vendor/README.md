# _vendor/ — pinned drop-in from netcanon-dev/ui-design-spec

Vendored, byte-pinned copies of the unified UI deliverable.  **Never edit these
files by hand** — they are generated in the spec repo and pinned here by sha256;
to change anything, bump the pin to a newer spec tag and re-copy.

| File | Source (in spec repo) | sha256 |
|---|---|---|
| `netcanon-ui.css` | `dist/netcanon-ui.css` | `0cc326194373fa6ba8d19a281e0946043a6c056a1dbe9b6ec9bbd0940fe40e68` |
| `theme-picker.js` | `dist/theme-picker.js` | `eb49114e4e921abb749490400d3085af93d86042f0f135031214c8bfe4bc69a8` |
| `compat-netcanon.css` | `dist/compat/netcanon.css` | `25e9bd3876a1263ca088a61eff427a4c347ff7aee829767b68761f018463c362` |

**Pinned tag:** `v0.2.1` (peels to commit `1c4af32911e0ddc370a4a3049112adb4e35e8f7f`
via `git rev-parse 'v0.2.1^{commit}'`) of netcanon-dev/ui-design-spec.

These files are Jinja-`{% include %}`d inline by `templates/base.html` (same
mechanism as `_partials/*.js` — netcanon serves no static files).  They contain
no Jinja delimiters, so the include splices them verbatim.  A `.gitattributes`
rule (`/netcanon/templates/_vendor/* -text`) exempts them from EOL conversion so
the checksums above stay true on every checkout.

To re-vendor at a newer tag:

    git -C <spec-repo> show <tag>:dist/netcanon-ui.css     > netcanon-ui.css
    git -C <spec-repo> show <tag>:dist/theme-picker.js     > theme-picker.js
    git -C <spec-repo> show <tag>:dist/compat/netcanon.css > compat-netcanon.css

then update this README's tag + sha256 table (and the CHANGELOG) in the same
commit.  See `dist/README.md` in the spec repo for the integration model.
