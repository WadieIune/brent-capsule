"""Experimentos de aplicaciones de Riesgo de Mercado sobre la geometría del canal."""
from .dq_price_control import DQPriceControlExperiment
from .channel_vol_forecast import ChannelVolForecastExperiment
from .predicted_var import PredictedVaRExperiment
from .portfolio_var import PortfolioVaRExperiment
from .portfolio_var_alert import PortfolioVaRAlertExperiment
from .frtb_applications import FRTBApplicationsExperiment
from .frtb_capital import FRTBCapitalExperiment
from .dq_impact import DQImpactExperiment
from .breakout_detection import BreakoutDetectionExperiment
from .regime_markov import RegimeMarkovExperiment
from .dq_daily_monitor import DQDailyMonitorExperiment
<<<<<<< Updated upstream
=======
from .dq_synthetic_validation import DQSyntheticValidationExperiment
from .channel_vol_audit import ChannelVolAuditExperiment
from .dq_capital_impact import DQCapitalImpactExperiment
>>>>>>> Stashed changes

ALL_EXPERIMENTS = [
    DQPriceControlExperiment,
    ChannelVolForecastExperiment,
    PredictedVaRExperiment,
    PortfolioVaRExperiment,
    PortfolioVaRAlertExperiment,
    FRTBApplicationsExperiment,
    FRTBCapitalExperiment,
    DQImpactExperiment,
    BreakoutDetectionExperiment,
    RegimeMarkovExperiment,
    DQDailyMonitorExperiment,
<<<<<<< Updated upstream
=======
    DQSyntheticValidationExperiment,
    ChannelVolAuditExperiment,
    DQCapitalImpactExperiment,
>>>>>>> Stashed changes
]

__all__ = [c.__name__ for c in ALL_EXPERIMENTS] + ["ALL_EXPERIMENTS"]
