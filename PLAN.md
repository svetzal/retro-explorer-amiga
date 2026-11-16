# Active plan

Keep this file limited to open work. Remove each item when its acceptance
criteria are met. Keep its evidence in the relevant guide or example. Nobody
is working on these items now unless the item says so.

## Continue from here

Read [AGENTS.md](AGENTS.md), then choose one open item below. Use the
[guidance map](guidance/README.md) for the current guides. Preserve the
ignored `local/` and `build/` folders and the prepared `.venv`.

## Open work

- **Amiberry control and recording.** Establish which controls and
  measurements Amiberry gives this pattern. These include loading a
  program, running to a checkpoint, scripted input, memory snapshots, frame
  capture and audio capture. Record each one in
  [the evidence the tools collect](guidance/starter/toolchain.md#evidence-the-tools-collect)
  with a check that has a failure control. Prior work in the `amiga-llm`
  repository has evidence about Amiberry. Read it as a lead, and check each
  result again here before you rely on it.
- **Technique guides.** There are none yet. The first guides come from labs
  and BUILD work, as the [technique index](guidance/techniques/README.md)
  describes. Do not write guides ahead of a concrete need.
- **Examples beyond a first screen.** A first example sets up a screen. Each
  later example comes from a lab or a project that needs it. Obey
  [the rules for examples](examples/AGENTS.md).
- **Reference collection.** Choose the first sources in `resources.json`.
  Separate the material that is free to redistribute from the owner's
  licensed manuals. Check the conversion quality of the difficult pages,
  such as register tables and assembly listings.
- **Host onboarding.** No check establishes the first run on a clean host.
  Linux host onboarding is not checked. Record the result for each host in
  [supported hosts](guidance/starter/toolchain.md#supported-hosts).
- **The `a1200` target.** Its 68020 and AGA settings need their own checks.
  A result on `a500` does not establish `a1200` behaviour.
- **Physical hardware.** No path exists to run or measure a program on a real
  Amiga. Emulator checks keep their stated limits until one does.

Out of scope: any download of Kickstart ROMs or licensed manuals from the
internet. The owner supplies their own licensed copies.
