# pace (slot)

Pace is built by a partner team and will be vendored here at a pinned commit with `vendor/vendor.py`. Until then
this folder holds only this note. What pace does is described in `rules/joint-system.md`, section 3.

When it lands: `python3 vendor/vendor.py lock pace --source <checkout> --from <path> --to pace --copy`, and
`vendor.lock.json` records the commit and a checksum of every file.
