"""Compare native SVG icons with generated references, without tracing pixels.

Foreground IoU ignores white background agreement. Both silhouettes are cropped
and aspect-preservingly fitted to the same canvas; no translation/warp search.
"""
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import cairosvg
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('pitch', 'insight', 'track')
MIN_IOU = 0.80


def mask(image):
    rgba = image.convert('RGBA')
    background = Image.new('RGBA', rgba.size, 'white')
    background.alpha_composite(rgba)
    return background.convert('L').point(lambda p: 255 if p < 128 else 0)


def normalize(image):
    foreground = mask(image)
    box = foreground.getbbox()
    if not box:
        raise ValueError('Icon has no foreground')
    foreground = foreground.crop(box)
    foreground.thumbnail((128, 128), Image.Resampling.LANCZOS)
    result = Image.new('L', (144, 144))
    result.paste(foreground, ((144 - foreground.width) // 2, (144 - foreground.height) // 2))
    return result.point(lambda p: 255 if p >= 128 else 0)


def complexity(path):
    tree = ET.parse(path)
    allowed = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'}
    shapes = commands = coordinates = 0
    for node in tree.iter():
        tag = node.tag.rsplit('}', 1)[-1]
        if tag not in allowed:
            raise ValueError(f'{path.name}: disallowed {tag}; no raster embedding or filters')
        if any(key.lower().startswith('on') or 'href' in key for key in node.attrib):
            raise ValueError(f'{path.name}: external content or executable attribute')
        if tag not in {'svg', 'g'}:
            shapes += 1
        commands += len(re.findall(r'[MmZzLlHhVvCcSsQqTtAa]', node.get('d', '')))
        # SVG allows implicit repeated commands and point lists: command letters
        # alone would let dense pixel traces hide inside one path or polygon.
        coordinates += len(re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?',
                                      node.get('d', '') + ' ' + node.get('points', '')))
    if shapes > 8 or commands > 40 or coordinates > 160 or path.stat().st_size > 2048:
        raise ValueError(f'{path.name}: exceeds native geometry budget')
    return shapes, commands


def main():
    sheet = Image.open(ROOT / 'assets/reference/icon-sheet.png')
    results = []
    preview = Image.new('RGB', (144 * 3, 144 * 3), 'white')
    for index, name in enumerate(NAMES):
        path = ROOT / f'assets/icons/{name}.svg'
        shapes, commands = complexity(path)
        reference = normalize(sheet.crop((sheet.width * index // 3, 0, sheet.width * (index + 1) // 3, sheet.height)))
        rendered = Image.open(io.BytesIO(cairosvg.svg2png(url=str(path), output_width=512, output_height=512)))
        actual = normalize(rendered)
        intersection = sum(ImageChops.darker(reference, actual).histogram()[1:])
        union = sum(ImageChops.lighter(reference, actual).histogram()[1:])
        iou = intersection / union
        results.append({'icon': name, 'foreground_iou': round(iou, 4), 'minimum': MIN_IOU, 'shapes': shapes, 'path_commands': commands, 'passed': iou >= MIN_IOU})
        preview.paste(ImageChops.invert(reference).convert('RGB'), (index * 144, 0))
        preview.paste(ImageChops.invert(actual).convert('RGB'), (index * 144, 144))
        # Reference in red, SVG in cyan, intersection black.
        preview.paste(Image.merge('RGB', (ImageChops.invert(actual), ImageChops.invert(reference), ImageChops.invert(reference))), (index * 144, 288))
    output = ROOT / 'assets/reference'
    preview.save(output / 'icon-comparison.png')
    (output / 'icon-results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
    return 0 if all(row['passed'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
