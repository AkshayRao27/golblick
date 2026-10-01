# Contributing

Issues and pull requests are welcome. This is a hobby project that is almost entirely written by LLMs (see the disclaimer in the [README](README.md)), so I can't promise when, or whether, I'll get to something that doesn't affect the cameras I use. Reports with clear evidence get looked at first.

## Testing a camera I don't have

This is the most useful contribution right now. Everything has been tested on stills from three cameras: the Insta360 OneR, X3 and X5. I can't test anything else, and other models may well store things differently: each of those three differs from the other two in some way the reader has to handle.

If you have a different 360 camera, or one of those three with different firmware, please try this:

1. Install with rendering support: `uv tool install 'kugelblick[render]'` (or `pipx install 'kugelblick[render]'`).
2. Run `kugelblick probe <file>` on a few stills. If it fails, the error message is the useful part.
3. Run `kugelblick render <file> -o test.jpg` and look at the result in a 360 viewer, or as a flat image. Check that it is upright and not mirrored (text in the scene is the easiest tell), that horizons and straight lines continue across the seam where the two lenses meet, and what the *lens agreement* line says. Around +0.7 to +0.9 is a correct projection, and near +0.02 means the geometry is wrong.
4. If `kugelblick preview <file>` reports an equirectangular preview, your camera embeds its own stitch, and comparing the two is very helpful.

Then open an issue with the camera model and firmware, the command output, and what you saw. A crop of the seam is enough; you don't need to share whole photos.

⚠️ `probe` prints the camera's serial number. Delete that line before posting. `probe -v` also prints the calibration values, which are specific to your camera body. They are very useful for working out how a new model stores its lenses, so share them if you're comfortable with that, but it's your call.

Video (`.insv`) is not rendered yet, but `probe` and `triage` work on it, and reports on those are welcome too.

## Code

[docs/development.md](docs/development.md) covers setup, running the tests (with and without the render extra, both are required), the layout and the conventions. In short:

- The library and CLI stay free of dependencies; rendering is the exception, behind the `render` extra.
- A reader refuses a file it can't prove it understood rather than guessing.
- No real photos, videos or serial numbers go into the repository. Test fixtures are synthesised.
- A change to the projection is made in both the Python library and the PHP Nextcloud app.
- Commit messages explain why, not just what. Write paragraphs as single lines.

LLM-assisted contributions are fine; this project is one. [AGENTS.md](AGENTS.md) is written for a coding agent, so point yours at it.

## Licence

By contributing, you agree that your contribution is licensed under the same terms as the part of the repository it touches: MIT for everything except `nextcloud-app/`, which is AGPL-3.0-or-later.
