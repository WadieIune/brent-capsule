import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'code/applications/experiments'))
import numpy as np
from cnn_capital_images import fit_scaler, transform_window, joint_target


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.x = np.random.default_rng(71).normal(size=(160, 3))
        self.s = fit_scaler(self.x, 80)

    def test_future_invariance(self):
        before = transform_window(self.x, self.s, 100, 32)
        altered = self.x.copy()
        altered[101:] = 1e9
        np.testing.assert_array_equal(before['images'], transform_window(altered, self.s, 100, 32)['images'])
        other = fit_scaler(altered, 80)
        np.testing.assert_array_equal(self.s.center, other.center)
        np.testing.assert_array_equal(self.s.scale, other.scale)

    def test_algebra_and_shape(self):
        out = transform_window(self.x, self.s, 100, 32)
        self.assertEqual(out['images'].shape, (9, 32, 32))
        for j in range(3):
            a, d, m = out['images'][3*j:3*j+3]
            np.testing.assert_allclose(a, a.T)
            np.testing.assert_allclose(d, -d.T, atol=1e-7)
            recovered = np.sqrt((np.diag(a) + 1) / 2)
            np.testing.assert_allclose(recovered, out['bounded_window'][:, j], atol=1e-6)

    def test_missing_and_unseen_features(self):
        x = self.x.copy()
        x[:80, 2] = np.nan
        x[95, 0] = np.nan
        out = transform_window(x, fit_scaler(x, 80), 100, 32)
        self.assertTrue(np.isfinite(out['images']).all())
        self.assertEqual(out['images'][6:].sum(), 0)
        self.assertEqual(out['images'][2, 26].sum(), 0)
        self.assertEqual(out['images'][2, :, 26].sum(), 0)

    def test_constant_and_amplitude(self):
        x = np.ones((100, 2))
        s = fit_scaler(x, 50)
        first = transform_window(x, s, 70, 16)['images']
        x[55:71] = 3
        second = transform_window(x, s, 70, 16)['images']
        self.assertTrue(np.isfinite(first).all())
        self.assertFalse(np.array_equal(first, second))

    def test_joint_fx_direction_cross_term(self):
        b, f = np.full(12, 100.0), np.full(12, 1.2)
        b[10], f[10] = 110.0, 1.32
        _, cost = joint_target(b, f, 0)
        self.assertAlmostEqual(cost, 0.0)
        f[10] = 1.08
        _, cost = joint_target(b, f, 0)
        self.assertAlmostEqual(cost, 1.1 / 0.9 - 1)
        with self.assertRaises(ValueError):
            joint_target(b, f, 3)


if __name__ == '__main__':
    unittest.main()
