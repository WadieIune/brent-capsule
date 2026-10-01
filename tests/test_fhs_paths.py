import unittest
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code/applications/experiments'))
from fhs_paths import innovation_paths,simulate

class FHSTests(unittest.TestCase):
    def test_zero_innovation_zero_returns(self):
        np.testing.assert_array_equal(simulate(np.zeros((3,10,2)),np.array([.01,.02])),np.zeros((3,2)))

    def test_dynamic_variance_path(self):
        p=np.ones((1,2,1));p[0,0,0]=2
        expected=2*np.sqrt(.01)+np.sqrt(.94*.01+.06*.04)
        self.assertAlmostEqual(simulate(p,np.array([.01]))[0,0],expected)

    def test_no_use_after_library_end(self):
        rng=np.random.default_rng(7)
        prices=pd.DataFrame(np.exp(rng.normal(0,.01,(120,2)).cumsum(axis=0)),index=pd.bdate_range('2020-01-01',periods=120))
        before=innovation_paths(prices,[30,50],10)
        prices.iloc[61:]*=1e6
        np.testing.assert_array_equal(before,innovation_paths(prices,[30,50],10))

    def test_negative_variance_rejected(self):
        with self.assertRaises(ValueError):simulate(np.zeros((1,10,2)),np.array([-.1,.2]))

if __name__=='__main__': unittest.main()
