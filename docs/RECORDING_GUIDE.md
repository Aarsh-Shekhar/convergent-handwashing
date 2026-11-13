# Recording your own washing clips

These clips teach the model what the steps look like on our camera, and give us an honest
accuracy test. They stay on your Mac (`data/own/` is git-ignored).

Run the commands from your own Terminal app, in `~/convergent-handwashing`. Use the
`--device` number that shows the Mac webcam (usually 1).

## What happens in one round

The window shows a step name and a 5 second countdown. Then it records 15 seconds. Do that
one step for the whole 15 seconds. It repeats for 8 clips: the 7 steps, then "not washing".
One round takes about 3 minutes. Press Esc to stop early.

For the steps with a "switch halfway" hint, change hands about halfway through.

For "not washing": keep your hands in view but don't rub. Hold them apart, wave, reach
toward where a tap would be, shake them dry.

## Record 4 rounds

Laptop tilted down at your hands (like a faucet camera):

```bash
.venv/bin/python -m convergent.cli record --device 1 --view down --round down1
```

```bash
.venv/bin/python -m convergent.cli record --device 1 --view down --round down2
```

Hands held up in front of the screen:

```bash
.venv/bin/python -m convergent.cli record --device 1 --view front --round front1
```

```bash
.venv/bin/python -m convergent.cli record --device 1 --view front --round front2
```

Between rounds, change something small: move your hands to a different part of the picture,
change the distance, or change the lighting. Rounds `down2` and `front2` are held out as the
test set and never used for training.

## Redo one clip

```bash
.venv/bin/python -m convergent.cli record --device 1 --view down --round down1 --classes palm_to_palm
```

## Tips

- Keep both hands inside the picture the whole time.
- Rub at a normal speed, the way you would at a sink.
- If a teammate records too, give their rounds a new name, for example `sam_down1`.
