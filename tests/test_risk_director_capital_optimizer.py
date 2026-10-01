import importlib.util
import unittest
from pathlib import Path
import numpy as np

spec=importlib.util.spec_from_file_location('capital',str(Path(__file__).resolve().parents[1]/'code/applications/experiments/risk_director_capital_cnn.py'))
capital=importlib.util.module_from_spec(spec)
spec.loader.exec_module(capital)

class OptimizerTests(unittest.TestCase):
    def test_no_risk_no_capital_or_cost(self):
        result=capital.optimize(np.zeros((3,2)),np.ones(3)/3)
        self.assertEqual(result,(0.,0.,0.,0.,0.))

    def test_binding_constraints(self):
        result=capital.optimize(np.array([[.2,-.1],[.05,.01],[-.1,.03]]),np.ones(3)/3,budget=20000)
        self.assertLessEqual(result[1]+result[2],1)
        self.assertLessEqual(result[3]+result[4],20000)

    def test_more_budget_cannot_worsen_objective(self):
        y=np.array([[.3,-.1],[.1,-.03],[-.05,.04]])
        weights=np.ones(3)/3
        self.assertLessEqual(capital.optimize(y,weights,budget=150000)[0],capital.optimize(y,weights,budget=0)[0])

    def test_visual_sign_is_retained(self):
        a=capital.images(np.ones((1,2,8),dtype='float32'))
        b=capital.images(-np.ones((1,2,8),dtype='float32'))
        self.assertFalse(np.allclose(a,b))

if __name__=='__main__': unittest.main()
