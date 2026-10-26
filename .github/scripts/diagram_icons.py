"""Inline vector artwork: GitHub's raw SVG policy blocks data-URL images."""
from pathlib import Path
import xml.etree.ElementTree as ET

ASSETS = Path(__file__).resolve().parents[1] / 'diagram-assets'
ET.register_namespace('', 'http://www.w3.org/2000/svg')


def icon_svg(name, x, y, size):
    icon = ET.parse(ASSETS / f'{name}.svg').getroot()
    width, height = (float(icon.attrib[key]) for key in ('width', 'height'))
    icon.attrib.update(x=str(x), y=str(y), width=str(size), height=str(size),
                       viewBox=f'0 0 {width} {height}', preserveAspectRatio='xMidYMid meet')
    return ET.tostring(icon, encoding='unicode')


def inline_export_icons(path):
    """Replace Excalidraw's raster symbols with the same native vector artwork."""
    tree = ET.parse(path)
    for text in tree.getroot().iter('{http://www.w3.org/2000/svg}text'):
        text.set('font-family', 'Arial, Helvetica, sans-serif')
    for symbol in tree.getroot().iter():
        name = symbol.get('id', '').removeprefix('image-')
        if not (ASSETS / f'{name}.svg').exists():
            continue
        icon = ET.parse(ASSETS / f'{name}.svg').getroot()
        symbol.set('viewBox', f"0 0 {icon.get('width')} {icon.get('height')}")
        symbol.set('preserveAspectRatio', 'xMidYMid meet')
        for child in list(symbol):
            symbol.remove(child)
        symbol.extend(icon)
    tree.write(path, encoding='unicode')
