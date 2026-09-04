# Sprite guide

Everything needed to draw a Claude Cute character. It is written from the
default character's actual measurements, so any new character that follows it
will fit without touching code.

## Format

| | |
|---|---|
| Canvas | **128 × 128 px** |
| File | PNG with real transparency (RGBA) |
| Technique | Draw at **64 × 64** and export at **200% with nearest neighbour** |
| Names | `frame_01.png`, `frame_02.png`, … |
| Location | `assets/<character>/<state>/` |
| Case | **all lowercase**, folders and files alike |

### Lowercase is not a style preference

Windows does not tell `Idle` and `idle` apart, so a miscapitalised folder works
there. Linux does tell them apart, and there the folder simply does not answer.

What makes that dangerous is a design decision of the widget: **a state with no
drawings of its own is not an error — it inherits from its ancestor.** So the
mistake does not crash anything and nothing turns red. The dragon shows a
plausible animation that is not the one you drew, and on your machine it looks
perfect.

The worst version: a folder only counts as a character if it holds a
`character.json` or at least one folder named exactly like a state. Get every
folder's capitalisation wrong, with no sheet, and **the whole character
disappears from the menu** on Linux while working fine on Windows.

No smoothing on export. The widget scales without interpolation, so a sprite
that is already blurry stays blurry and there is no way back.

The canvas size is not hardcoded: the engine reads it from the first sprite it
loads. A 64 × 64 character with `"scale": 4` works just as well.

## The anchor

The most important rule, and the one that keeps the avatar from jumping when
the state changes.

```
            x=32                    x=95
             │                       │
    y=16 ────┼───────────────────────┼────   ceiling of the effects area
             │     EFFECTS AREA      │       (speech bubble)
    y=40 ────┼───────────────────────┼────
             │                       │
             │       THE BODY        │       64 px wide
             │                       │
    y=85 ────┴───────────────────────┴────   BASELINE — fixed in every frame
             │
    y=127 ───────────────────────────────
```

In the coordinates of the 64 × 64 drawing: **body between x 16–47, baseline at
y 42**.

Effects may leave the body's box, in two reserved areas:

- **Above**, y 16–40 (in 64 × 64: y 8–20) — where the `thinking` bubble lives
- **Left**, x 10–32 (in 64 × 64: x 5–16) — where the `working` flame comes out

## Palette

The nine colours of the original set. Keeping to them is what makes everything
look like it came from the same hand. The newer states added five more, listed
under "The palette grew".

| Colour | Role |
|---|---|
| `#151D28` | Body, dark base *(the dominant one)* |
| `#253A5E` | Mid blue: wings, details |
| `#172038` | Deep shadow |
| `#000000` | Pupils |
| `#DA863E` | Orange: flame |
| `#E8C170` | Yellow: flame highlight |
| `#C7CFCC` | Light grey: speech bubble |
| `#A8B5B2` | Mid grey: bubble shadow |
| `#EBEDE9` | Near white: highlights |

If a new state needs a colour that is not there, add few and in the same
register: dark and desaturated, or from the cyan range already used for the
effects.

## Loop, one-shot, or entry plus loop

Three ways to play, and they change how the last frame is drawn.

**Loop.** Repeats indefinitely. The last frame has to return naturally to the
first.

**One-shot.** Plays once and **freezes on the last frame** until the state
expires. These are transitions, so the last frame has to match the first frame
of whatever comes next:

| State | Its last frame connects to |
|---|---|
| `wake` | `idle/frame_01` |
| `done` | `idle/frame_01` |
| `error` | `idle/frame_01` |
| `sleep` | `idle-sleep/frame_01` — the dragon already lying down, no Zs |

One-shot states have a time budget. Go over it and the animation gets cut in
half — and the program **warns you at startup**:

```
[claude-cute] heads up: 'wake' lasts 1800 ms but expires at 1200 ms; it will be cut short.
```

| State | Budget | Max frames at its speed |
|---|---|---|
| `wake` | 1200 ms | 8 (150 ms each) |
| `done` | 1300 ms | 8 (160 ms each) |
| `error` | 1200 ms | 10 (110 ms each) |
| `sleep` | 1400 ms | 7 (200 ms each) |

Loops have no cap.

### Entry plus loop

An opening that plays once, and then a shorter tail that repeats for as long as
the state lasts. `dragged` is drawn this way: the dragon is lifted, and then it
sways in your hand.

Say where the tail begins in `character.json`, **counting from 1 like the file
names**:

```json
"loop_from": { "dragged": 6 }
```

With seven frames and the tail starting at six, what plays is:

```
1 2 3 4 5 6 7 6 7 6 7 …
```

Two things worth knowing:

- **The opening plays again every time the state is entered.** Pick the avatar
  up, drop it, pick it up again, and the lift replays. That is usually what you
  want; if it is not, put the loop point at 1.
- **Only frame 1 has to connect to the tail's last frame**, instead of the
  whole animation having to close on itself. That is the freedom this buys.

It works on one-shot states too, where it replaces the frozen pose with a
subtle idle: `"loop_from": {"done": 3}` keeps `done` breathing until it
expires. Same rule everywhere, because it describes the drawing and not the
kind of state.

A number outside the range is ignored and the animation loops from the start —
so a typo costs you the effect, not a dragon stuck on the wrong frame.

There is a warning for the opposite case too: if the animation is much shorter
than the budget, the final pose is held for so long it reads as a hang. The
rule the current timings follow is **animation plus roughly 600 ms of held
pose**.

## The list

| Folder | Frames | Type | What it shows |
|---|---|---|---|
| `idle` | 4 ✅ | loop | Resting. Gentle breathing |
| `idle-sleep` | 4 ✅ | loop | Asleep. Zs pile up. Starts after 5 min of inactivity |
| `thinking` | 6 ✅ | loop | Reasoning. Bubble with dots |
| `working` | 6 ✅ | loop | Fallback for tools with no animation of their own |
| `working-bash` | 6 ✅ | loop | Terminal command |
| `working-edit` | 6 ✅ | loop | Writing files |
| `working-read` | 6 ✅ | loop | Reading and searching |
| `working-web` | 6 ✅ | loop | Browsing |
| `working-agent` | 6 ✅ | loop | Delegating to subagents |
| `waiting` | 6 ✅ | loop | **Claude is waiting for you** |
| `done` | 4 ✅ | one-shot | Finished |
| `error` | 5 ✅ | one-shot | Something failed |
| `error-api` | — | — | **Do not draw.** Inherits from `error` |
| `wake` | 4 ✅ | one-shot | Session starts. Opens an eye and sits up |
| `sleep` | 4 ✅ | one-shot | Session ends. **Lies down**: the act of falling asleep, not sleeping |
| `compacting` | 6 ✅ | loop | Tidying its memory. Arranging its hoard |

✅ done

**`dragged` is the sixteenth folder, and the only one that is not the
session's.** It plays while you carry the avatar across the desk, and it is the
one animation you are guaranteed to actually watch, since you are looking
straight at the dragon while you drag it. Drawn as an entry plus a loop: seven
frames, tail from the sixth.

**The set is complete: 16 folders, 84 frames.** The only state with no drawing
of its own is `error-api`, and that is deliberate.

### Notes per state

**`error-api` is not drawn.** It inherits from `error` on purpose: an API
failure and a command failure look the same to the user.

**`sleep` and `idle-sleep` are different and easy to confuse.** `idle-sleep` is
the loop of being asleep, with the Zs piling up; `sleep` is the *lying down*
transition, which plays once when the session ends and connects into that loop.
If a new character only draws one of the two, `sleep` inherits from
`idle-sleep`.

## The palette grew

The newer states added these to the original nine:

| Colour | Where |
|---|---|
| `#73BED3` | Cyan: effects for `working-bash`, `-read`, `-web`, `-agent` |
| `#3C5E8B` | Mid blue: shadows for those same effects |
| `#4F8FBA` | Blue: detail on `working-edit` |
| `#202E37` | Dark blue-grey: shadow on `working-edit` |
| `#A53030` | Red: the question mark in `waiting` |

Cyan works as the "machine colour" and orange stays the dragon's; that
separation is what makes the tool states readable at a glance.

## You do not have to draw everything at once

The engine resolves by inheritance: a state without its own sprites uses those
of its nearest ancestor.

```
working-bash  ->  working  ->  idle
waiting       ->  thinking ->  idle
```

So states can be drawn one at a time and the widget is never broken. Every
folder completed improves one part while the rest keeps working.

At startup it reports where things stand:

```
[claude-cute] character: Dragoncita (128px x2)
[claude-cute] own sprites (15): idle, idle-sleep, thinking, working, ...
[claude-cute] inheriting from an ancestor: error-api
```

And **right click -> Force state** shows the full list, marking with
`· inherited` the ones that have no drawing of their own yet. It doubles as a
checklist.

While drawing, **right click -> Reload assets** re-reads the PNGs from disk
without restarting the widget: save the file and see it instantly.

## The character sheet

`assets/<character>/character.json` is optional. Without it the defaults are
used.

```json
{
  "name": "Dragoncita",
  "author": "Emmanuel Unsc",
  "scale": 2,
  "ms_per_frame": {
    "idle": 220,
    "thinking": 120,
    "working": 100
  }
}
```

| Field | What for |
|---|---|
| `name` | How it appears in the menu. If missing, the folder name is used |
| `author` | Attribution |
| `scale` | Size multiplier. **Whole number**, or the pixel art comes out uneven |
| `ms_per_frame` | Speed per state. A state with no entry inherits its ancestor's |

## A new character

1. Create `assets/<name>/`
2. Draw at least `idle/` — everything else can inherit
3. Optionally add `character.json`
4. It shows up on its own under **right click -> Character**

With four folders (`idle`, `thinking`, `working`, `done`) you already have a
perfectly usable character.
