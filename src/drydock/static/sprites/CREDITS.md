# Where this art came from

The pixel art in this directory is **CC0 1.0 Universal** (public domain): it may
be used, changed and redistributed by anyone, for anything, with no permission
and no attribution required.

Credit is given anyway, because being allowed not to is not a reason not to.

- **MetroCity top-down character pack** — [JIK-A-4](https://jik-a-4.itch.io/metrocity-free-topdown-character-pack),
  CC0 1.0 Universal. The characters, the furniture, the floors and the walls.
- The sheets were taken from **[pixel-agents](https://github.com/pixel-agents-hq/pixel-agents)**
  by Pablo De Lucca (MIT), which had already separated the pack into the layered
  form used here. Nothing of that project's own code is included.

## The sheet format

Each character layer is one 128x96 sheet of 16x32 frames: 8 columns by 3 rows.

| | |
|---|---|
| Rows | `down`, `up`, `right` (left is `right` mirrored) |
| Columns 0-2 | the walk cycle, played `0 1 2 1` |
| Columns 3-4 | typing |
| Columns 5-6 | reading |
| Column 7 | seated, doing nothing |

Layers are drawn in order — body, pants, shoes, top, hair — and the top layer
is tinted per person, which is how seven people wearing one shirt end up
looking like seven people.
