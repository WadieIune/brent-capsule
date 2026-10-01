"""Joint daily EWMA filtered historical simulation; past-only volatilities."""
import numpy as np
import pandas as pd

def innovation_paths(prices, starts, horizon=10, decay=.94):
    returns=np.log(prices).diff()
    known_var=returns.pow(2).ewm(alpha=1-decay,adjust=False,min_periods=20).mean().shift(1)
    innovations=returns/np.sqrt(known_var.clip(lower=1e-12))
    paths=np.stack([innovations.iloc[i+1:i+horizon+1].to_numpy() for i in starts])
    if paths.shape!=(len(starts),horizon,prices.shape[1]) or not np.isfinite(paths).all():
        raise ValueError('Incomplete or nonfinite innovation paths')
    return paths

def simulate(paths, initial_variance, decay=.94):
    if not np.isfinite(initial_variance).all() or (initial_variance<0).any():
        raise ValueError('Invalid conditional variance')
    variance=np.broadcast_to(initial_variance,(len(paths),paths.shape[2])).copy()
    total=np.zeros_like(variance)
    for k in range(paths.shape[1]):
        r=paths[:,k]*np.sqrt(np.maximum(variance,1e-12))
        total+=r
        variance=decay*variance+(1-decay)*r*r
    return total
