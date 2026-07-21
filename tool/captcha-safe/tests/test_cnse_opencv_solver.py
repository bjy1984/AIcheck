import io
import unittest

import numpy as np
from PIL import Image

from cnse_opencv_solver import CnseOpenCvError, solve_opencv_from_bytes


def png_bytes(array):
    output = io.BytesIO()
    Image.fromarray(array, mode="RGBA").save(output, format="PNG")
    return output.getvalue()


class CnseOpenCvSolverTests(unittest.TestCase):
    def test_masked_photometric_match_returns_extension_coordinates(self):
        rng = np.random.default_rng(42)
        background = np.full((80, 140, 4), 255, dtype=np.uint8)
        background[:, :, :3] = rng.integers(30, 225, size=(80, 140, 3), dtype=np.uint8)
        left, top = 73, 29
        puzzle = background[top : top + 25, left : left + 31].copy()
        puzzle[:, :, 3] = 0
        puzzle[3:-3, 3:-3, 3] = 255

        result = solve_opencv_from_bytes(png_bytes(puzzle), png_bytes(background))

        self.assertEqual((result.left, result.top), (left, top))
        self.assertEqual((result.target_x, result.target_y), (88, 41))
        self.assertEqual(result.strategy, "masked-photometric")
        self.assertGreater(result.confidence, 0.99)

    def test_rejects_low_confidence_or_invalid_inputs(self):
        flat_background = np.full((40, 80, 4), 255, dtype=np.uint8)
        flat_puzzle = np.full((10, 12, 4), 255, dtype=np.uint8)
        with self.assertRaises(CnseOpenCvError):
            solve_opencv_from_bytes(png_bytes(flat_puzzle), png_bytes(flat_background))
        with self.assertRaises(CnseOpenCvError):
            solve_opencv_from_bytes(b"not an image", png_bytes(flat_background))


if __name__ == "__main__":
    unittest.main()
