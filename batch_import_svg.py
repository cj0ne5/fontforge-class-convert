# Batch Import SVG Individual Glyph Files into FontForge's Font File
# Run with FontForge's own Python: `fontforge -script batch_import_svg.py <SVG_FOLDER> <OUTPUT_BASE> [FONT_NAME]`
# e.g. `fontforge -script batch_import_svg.py SVG output` writes output.sfd and output.otf
# (sync_drive.py calls this once per student folder)

import sys
import re
import os
import pickle
import signal
import tempfile
import fontforge
from pathlib import Path

svgFolder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('SVG')
outputBase = sys.argv[2] if len(sys.argv) > 2 else 'output'
fontName = sys.argv[3] if len(sys.argv) > 3 else 'Untitled'

SIDE_BEARING = 40 # empty space on each side of a letter, in font units (1000 = the letter height box)
SPACE_WIDTH = 300 # width of the space character
OVERLAP_TIMEOUT = 20 # seconds; FontForge's overlap removal can hang forever on dense scribbles

font = fontforge.font() # new font
font.encoding = 'UnicodeFull' # the default is Latin-1, which merges letters like zcaron (382) into existing glyphs
font.familyname = fontName
font.fullname = fontName
font.fontname = re.sub(r'[^A-Za-z0-9-]', '', fontName) or 'Untitled' # PostScript name: ASCII, no spaces

SHAPE = re.compile(r'<(?:path|line|polyline|polygon|rect|circle|ellipse)\b[^>]*>')


def inline_css(svg):
	"""FontForge ignores <style> classes, so copy each class's rules into a style attribute on the elements that use it."""
	css = ''.join(re.findall(r'<style[^>]*>(.*?)</style>', svg, re.S))
	rules = {}
	for selectors, body in re.findall(r'([^{}]+)\{([^}]*)\}', css):
		for sel in selectors.split(','):
			sel = sel.strip()
			if sel.startswith('.'):
				rules[sel[1:]] = rules.get(sel[1:], '') + ' '.join(body.split()).rstrip(';') + ';'
	if not rules:
		return svg
	return re.sub(r'class="([^"]*)"', lambda m: 'style="' + ''.join(rules.get(c, '') for c in m.group(1).split()) + '"', svg)


def paint(tag):
	"""(fill, stroke, stroke width) of an SVG shape element, from its attributes and style."""
	props = dict(re.findall(r'\s(fill|stroke|stroke-width)="([^"]*)"', tag))
	style = re.search(r'style="([^"]*)"', tag)
	if style:
		for decl in style.group(1).split(';'):
			if ':' in decl:
				key, value = decl.split(':', 1)
				props[key.strip()] = value.strip()
	width = re.match(r'[\d.]+', props.get('stroke-width', '1'))
	return props.get('fill', 'black'), props.get('stroke', 'none'), float(width.group()) if width else 1.0


def keep_shapes(svg, keep, style):
	"""svg with only the shape elements for which keep(tag) is true, each painted with style instead of its own paint
	('fill:none;stroke:none' makes FontForge import bare outlines, keeping open paths open)."""
	def repl(m):
		if not keep(m.group()):
			return ''
		tag = re.sub(r'\s(?:class|style|fill|stroke|stroke-width)="[^"]*"', '', m.group())
		return re.sub(r'^<(\w+)', r'<\1 style="' + style + '"', tag)
	return SHAPE.sub(repl, svg)


def import_text(glyph, svg):
	fd, tmp = tempfile.mkstemp(suffix='.svg')
	try:
		with os.fdopen(fd, 'w', encoding='utf-8') as fh:
			fh.write(svg)
		glyph.importOutlines(tmp)
	finally:
		os.unlink(tmp)


def import_svg(glyph, path):
	"""Import filled shapes as they are. Stroked shapes (e.g. drawn with the pen tool, fill: none) are imported as
	centerlines and stroked here: FontForge's own SVG stroking hangs on scribbly strokes."""
	svg = inline_css(path.read_text(encoding='utf-8'))
	shapes = [paint(tag) for tag in SHAPE.findall(svg)]
	if all(stroke == 'none' for _, stroke, _ in shapes):
		import_text(glyph, svg)
		return
	viewbox = re.search(r'viewBox="[\d.\s-]+?\s([\d.]+)"', svg)
	scale = font.em / float(viewbox.group(1)) if viewbox else 1.0
	if any(fill != 'none' for fill, _, _ in shapes):
		import_text(glyph, keep_shapes(svg, lambda tag: paint(tag)[0] != 'none', 'fill:black;stroke:none'))
	scratch = font.createChar(-1, '_scratch')
	for width in sorted({w for _, stroke, w in shapes if stroke != 'none'}):
		scratch.clear()
		import_text(scratch, keep_shapes(svg, lambda tag: paint(tag)[1] != 'none' and paint(tag)[2] == width, 'fill:none;stroke:none'))
		scratch.stroke('circular', width * scale, 'round', 'round', removeoverlap='none')
		glyph.foreground += scratch.foreground
	font.removeGlyph(scratch)


def drop_spillover(glyph):
	"""Each SVG is one cell of the template, and Illustrator also exports parts of neighbouring letters that cross
	into the cell (e.g. the start of W in V's file). Drop contours centred outside the cell, unless nothing is left."""
	def inside(contour):
		xmin, _, xmax, _ = contour.boundingBox()
		return 0 <= (xmin + xmax) / 2 <= font.em
	kept = [c for c in glyph.foreground if inside(c)]
	if kept and len(kept) < len(glyph.foreground):
		layer = fontforge.layer()
		for c in kept:
			layer += c
		glyph.foreground = layer


def merge_overlaps(glyph):
	"""Merge overlapping strokes into one outline so small sizes don't render overlaps as white.
	removeOverlap() can hang, so run it in a forked child with a time limit; returns False if it didn't finish."""
	read, write = os.pipe()
	pid = os.fork()
	if pid == 0:
		os.close(read)
		signal.alarm(OVERLAP_TIMEOUT)
		glyph.removeOverlap()
		with os.fdopen(write, 'wb') as fh:
			pickle.dump([(c.closed, [(pt.x, pt.y, pt.on_curve) for pt in c]) for c in glyph.foreground], fh)
		os._exit(0)
	os.close(write)
	with os.fdopen(read, 'rb') as fh:
		data = fh.read()
	_, status = os.waitpid(pid, 0)
	if status != 0:
		return False
	layer = fontforge.layer()
	for closed, points in pickle.loads(data):
		contour = fontforge.contour()
		for x, y, on_curve in points:
			contour += fontforge.point(x, y, on_curve)
		contour.closed = closed
		layer += contour
	glyph.foreground = layer
	return True


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
		import_svg(glyph, p)
		drop_spillover(glyph)
		if merge_overlaps(glyph):
			glyph.correctDirection()
		else:
			print(f'WARNING (could not merge overlapping strokes; may show gaps where they cross): {p.name}')
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
