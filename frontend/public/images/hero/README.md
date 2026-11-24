# Landing-page hero photograph

The landing page shows a photograph here when `hero.json` exists. **None is included**: a real photograph needs a licence and, for people in it, consent.
Until you add one, the hero's right column shows the platform's live open needs instead (never a stand-in picture).

## Choose the photo
* Documentary style, natural light, real people: volunteers handing out food, clothing, books or supplies.
* Dignity first: no child shown in distress, no identifiable child without a guardian's written consent, no staged or AI-generated faces.
* You must hold the right to use it: your own photo with written consent, or one under a licence that allows website use (for example CC0 / Unsplash / Pexels licence).
  Keep the licence text and the source URL.
* Landscape, at least 1200 px wide.

## Add it
```powershell
pip install pillow
python scripts\make_hero_assets.py C:\path\photo.jpg --alt "Describe what the photo shows" --credit "Photo: Name" --license "Licence or permission" --source-url https://where-it-came-from
```
This writes `hero-1600.jpg/.webp`, `hero-800.jpg/.webp` and `hero.json` here, strips location and camera metadata, and the page picks it up on reload.

## Remove it
Delete `hero.json`: the page goes back to showing live open needs.

## Choosing the photograph for the new hero layout
The hero puts the words on the LEFT and the picture on the RIGHT (the overlay is darkest on the left, so any photo stays readable).
* Compose for it: the subject should sit in the right half of the frame (the CSS anchors the image at 72% / 30%).
* Use only images you have the right to use AND, for a photo of a child, a signed consent from the child's guardian or the
  organization that cares for them. Do not use stock-template images, screenshots of other websites, or images found online.
* Prefer dignified, hopeful images (children learning, playing, volunteers and children together, a delivered parcel being
  opened) over images of distress. Never show a child's name, uniform crest, address or anything that identifies where they live.
* Add the file and `hero.json` as described above, with the credit and licence; they are printed in the hero as the licence requires.
