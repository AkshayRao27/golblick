# Contributing

Issues and pull requests are welcome. This is a hobby project that is almost entirely written by LLMs (see the disclaimer in the [README](README.md)), so I can't promise when, or whether, I'll get to something that doesn't affect the cameras I use. I'll most likely point my instance of Claude Code at new issues, and it will probably pick up reports with clear evidence first.

## Testing a camera I don't have

This is the most useful contribution right now. Everything has been tested on stills from three cameras: the Insta360 OneR, X3 and X5. I can't test anything else, and other models may well store things differently: each of those three differs from the other two in some way the reader has to handle.

If you have a different 360 camera, please try this:

1. Install with rendering support: `uv tool install 'golblick[render]'` (or `pipx install 'golblick[render]'`).
2. Run `golblick report <file>` on a few stills. It prints a summary that is safe to paste into an issue: it leaves out the file's name, its folder and the camera's serial number. If something fails, the report says where, and carries on. It also prints a link that opens the issue with the report filled in.
3. Run `golblick render <file> -o test.jpg` and look at the result in a 360 viewer, or as a flat image. Check that it is upright and not mirrored (text in the scene is the easiest tell), that horizons and straight lines continue across the seam where the two lenses meet, and what the *lens agreement* line says. Around +0.7 to +0.9 is a correct projection, and near +0.02 means the geometry is wrong.
4. If `golblick preview <file>` reports an equirectangular preview, your camera embeds its own stitch, and comparing the two is very helpful.

Then [open an untested-camera issue](https://github.com/AkshayRao27/golblick/issues/new?template=untested-camera.yml) with the reports and what you saw; the link `report` prints opens it already filled in. Please do this even if everything looks right.

The report shows whether golblick can read the camera's files. Supporting it properly (the lens's field of view and correction, and which way its motion sensor faces) is measured from a few original photos, so if you can, say in the issue that you can share some. You'll get a private upload link in a reply. Don't attach photos to the issue or post links to them: issues are public, and an original `.insp` holds where the photo was taken, when, and the camera's serial number. Run `golblick share <files>` first, which writes copies without those and changes nothing else. The pictures themselves are unchanged, so choose ones you're happy to send: outdoors with a level horizon and some text in view is ideal, because text is the easiest way to spot a mirrored render.

For a problem with a photo from one of the three tested cameras, use the [photo problem form](https://github.com/AkshayRao27/golblick/issues/new?template=photo-problem.yml) instead. `report` picks the right one for you.

`golblick probe -v` also prints the calibration values, which are specific to your camera body. They are very useful for working out how a new model stores its lenses, so share them if you're comfortable with that, but it's your call. `probe` prints the camera's serial number too, so delete that line before posting its output.

Video isn't rendered yet, but `triage`, `probe` and `report` work on it, and reports on those are welcome too.

## Code

[docs/development.md](docs/development.md) covers setup, running the tests (with and without the render extra, both are required), the layout and the conventions. In short:

- The library and CLI stay free of dependencies; rendering is the exception, behind the `render` extra.
- A reader refuses a file it can't prove it understood rather than guessing.
- No real photos, videos or serial numbers go into the repository. Test fixtures are synthesised.
- A change to the projection is made in both the Python library and the PHP Nextcloud app.
- Commit messages explain why, not just what. Write paragraphs as single lines.

LLM-assisted contributions are fine; this project is fully vibe-coded anyway. [AGENTS.md](AGENTS.md) is written for a coding agent, so point yours at it.

## Licence

By contributing, you agree that your contribution is licensed under AGPL-3.0-or-later, like the rest of the repository.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
