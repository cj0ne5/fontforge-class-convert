# Batch Import SVG Individual Glyph Files into FontForge's Font File
# Run with FontForge's own Python: `fontforge -script batch_import_svg.py <SVG_FOLDER> <OUTPUT_BASE> [FONT_NAME]`
# e.g. `fontforge -script batch_import_svg.py SVG output` writes output.sfd and output.otf
# (sync_drive.py calls this once per student folder)

import sys
import re
import fontforge
from pathlib import Path

svgFolder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('SVG')
outputBase = sys.argv[2] if len(sys.argv) > 2 else 'output'
fontName = sys.argv[3] if len(sys.argv) > 3 else 'Untitled'

SIDE_BEARING = 40 # empty space on each side of a letter, in font units (1000 = the letter height box)
SPACE_WIDTH = 300 # width of the space character

font = fontforge.font() # new font
font.familyname = fontName
font.fullname = fontName
font.fontname = re.sub(r'[^A-Za-z0-9-]', '', fontName) or 'Untitled' # PostScript name: ASCII, no spaces

svgFilePaths = sorted(svgFolder.glob('**/*.svg'))
imported = 0

for p in svgFilePaths:
	# file names must start with the decimal Unicode codepoint, e.g. "65 A.svg"
	dec = p.stem.split(" ", 1)[0]
	if not dec.isdigit():
		print(f'SKIPPED (name does not start with a codepoint number): {p.name}')
		continue
	try:
		glyph = font.createChar(int(dec))
		glyph.importOutlines(str(p))
		# merge overlapping strokes into one outline so small sizes don't render overlaps as white
		glyph.removeOverlap()
		glyph.correctDirection()
		imported += 1
	except Exception as e:
		print(f'SKIPPED ({e}): {p.name}')

# every SVG is a full 1000-wide template cell, so glyphs inherit whatever empty space surrounded the drawing;
# fit each glyph's width to its outline instead, with the same small gap on both sides
drawn = [g for g in font.glyphs() if len(g.foreground) > 0]
for glyph in drawn:
	glyph.left_side_bearing = SIDE_BEARING
	glyph.right_side_bearing = SIDE_BEARING

# automatic kerning: tighten pairs like "To" or "AV" whose shapes leave a visibly larger gap than SIDE_BEARING
font.addLookup('kern', 'gpos_pair', None, (('kern', (('latn', ('dflt',)), ('DFLT', ('dflt',)))),))
font.addLookupSubtable('kern', 'kern-auto')
font.autoKern('kern-auto', SIDE_BEARING * 2, drawn, drawn, onlyCloser=True)

# the template has no space characters, so add blank ones; otherwise spaces show as boxes
for codepoint in (32, 160): # space, non-breaking space
	if codepoint not in font:
		font.createChar(codepoint).width = SPACE_WIDTH

# blank zero-width control characters; Word draws a box at every line break / empty paragraph without them
for codepoint, name in ((0, '.null'), (10, 'uni000A'), (13, 'nonmarkingreturn')):
	if codepoint not in font:
		font.createChar(codepoint, name).width = 0

print(f'Imported {imported} of {len(svgFilePaths)} SVG files')
if imported == 0:
	sys.exit(1)

font.save(outputBase + '.sfd')
font.generate(outputBase + '.otf')
