"""Experimentos de aplicaciones de Riesgo de Mercado sobre la geometría del canal."""
from .dq_price_control import DQPriceControlExperiment
from .channel_vol_forecast import ChannelVolForecastExperiment
from .predicted_var import PredictedVaRExperiment
from .portfolio_var import PortfolioVaRExperiment
from .frtb_applications import FRTBApplicationsExperiment

ALL_EXPERIMENTS = [
    DQPriceControlExperiment,
    ChannelVolForecastExperiment,
    PredictedVaRExperiment,
    PortfolioVaRExperiment,
    FRTBApplicationsExperiment,
]

__all__ = [c.__name__ for c in ALL_EXPERIMENTS] + ["ALL_EXPERIMENTS"]
