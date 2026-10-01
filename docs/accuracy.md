# How accuracy is measured

A stitch has to be checked against something, and every check here has a blind spot. This page says what each one sees and what it misses, because several wrong conclusions in this project came from trusting a number further than it could see.

## The self-check: lens agreement

The lenses see past 180°, so there is a band where both observe the same scene, and a correct projection makes those two views coincide. Correlating them over that band scores a render with no reference image at all, on any dual-fisheye camera. `kugelblick render` prints it as *lens agreement*.

On correctly projected stills it sits around +0.7 to +0.9, and a wrong rotation convention drops it to about +0.02. That makes it good at telling a right convention from a wrong one, and not much else. What it cannot see:

- It compares the lenses with each other, not with the world, so an upside-down or mirrored render can score well.
- A lens model that misplaces content the same way in both lenses moves both views together, so they still agree.
- A parameter fitted to it can absorb other errors. The field of view was fitted this way. The rule for the relative rotation between the lenses was confirmed with it, and turned out to be 0.44° wrong.
- It ranks how much texture a scene has as much as how well the seam lines up, so it cannot rank files by seam quality.

## Outside references

Two kinds of reference were not produced by this project:

- An X5 embeds a stitched, levelled panorama in every still, so X5 renders can be scored against the camera's own output.
- Insta360 Studio, the vendor's desktop app, was used to export stitched panoramas of the same files with stitching optimisation switched off. That gives a reference for the OneR and X3 too, which embed only the fisheye pair.

The useful measurement against either is per lens. Away from the seam, each lens appears alone in the reference, so a block of one lens matched to its place in the reference measures that lens's geometry with no blending involved. Splitting the displacement into radial and sideways parts, in each lens's own frame, then separates a lens-model error from a rotation error.

That is what found the two corrections described in the [format notes](formats/insta360.md). The first is the relative lens orientation, which the stored values give once each lens's angles are read in its own frame; correcting it makes the two lenses disagree 23% less in the overlap on a OneR, and stops horizons breaking at the seam. The second is the departure from the equidistant lens model, which moves content away from the seam rather than at it:

| OneR, scenes not used for fitting | Median displacement against Studio at 2048 wide |
|---|---|
| Equidistant model | 9.8 px |
| With the measured correction | 3.0 px |

Lens agreement could not see either.

## Levelling

Levelling is scored against the same outside references. Against Studio's levelled exports, the median horizon error is 1.0–1.2° on all three cameras, and 1,432 of 1,438 stills in the test library are levelled. The other six carry no trailer.

## Things that turned out to matter

- Weight seam measurements by area on the sphere. The seam passes through the zenith and the ground, where equirectangular pixels crowd together, so a per-pixel average can say a change made things worse when, on the sphere, it made them better.
- Put both sides of a comparison through the same pipeline. A box filter on one side and a Lanczos filter on the other was once measured as a regression in the thing being tested.
- A number that cannot see a defect will happily improve while the defect gets worse. When a seam setting is tuned to reduce disagreement between the lenses, it also needs a check that the seam does not become a visible line.
