"""Checks the comparison cannot pass by counting white background pixels."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw
from check_icons import complexity, normalize


class IconChecks(unittest.TestCase):
    def test_empty_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize(Image.new('RGB', (50, 50), 'white'))

    def test_normalization_preserves_aspect_ratio(self):
        image = Image.new('RGB', (100, 100), 'white')
        ImageDraw.Draw(image).rectangle((20, 10, 39, 49), fill='black')
        box = normalize(image).getbbox()
        self.assertEqual((box[2] - box[0]) * 2, box[3] - box[1])

    def test_solid_fill_does_not_match_outline(self):
        image = Image.new('RGB', (100, 100), 'white')
        ImageDraw.Draw(image).rectangle((10, 10, 90, 90), outline='black', width=5)
        outline = normalize(image)
        solid = normalize(Image.new('RGB', (100, 100), 'black'))
        intersection = sum(ImageChops.darker(outline, solid).histogram()[1:])
        union = sum(ImageChops.lighter(outline, solid).histogram()[1:])
        self.assertLess(intersection / union, 0.3)

    def test_raster_embedding_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'raster.svg'
            path.write_text('<svg><image href="data:image/png;base64,AAAA"/></svg>')
            with self.assertRaises(ValueError):
                complexity(path)

    def test_excessive_shapes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dense.svg'
            path.write_text('<svg>' + '<rect/>' * 9 + '</svg>')
            with self.assertRaises(ValueError):
                complexity(path)

    def test_implicit_segments_and_point_lists_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dense.svg'
            for shape in ('<path d="M0 0L' + '1 2 ' * 100 + '"/>',
                          '<polyline points="' + '1 2 ' * 100 + '"/>'):
                with self.subTest(shape=shape[:20]):
                    path.write_text('<svg>' + shape + '</svg>')
                    with self.assertRaises(ValueError):
                        complexity(path)


if __name__ == '__main__':
    unittest.main()
