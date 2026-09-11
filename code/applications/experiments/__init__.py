"""Experimentos de aplicaciones de Riesgo de Mercado sobre la geometría del canal."""
from .dq_price_control import DQPriceControlExperiment
from .channel_vol_forecast import ChannelVolForecastExperiment
from .predicted_var import PredictedVaRExperiment
from .portfolio_var import PortfolioVaRExperiment
from .portfolio_var_alert import PortfolioVaRAlertExperiment
from .frtb_applications import FRTBApplicationsExperiment
from .frtb_capital import FRTBCapitalExperiment
from .dq_impact import DQImpactExperiment
from .dq_daily_monitor import DQDailyMonitorExperiment
from .dq_synthetic_validation import DQSyntheticValidationExperiment
from .dq_capital_impact import DQCapitalImpactExperiment
from .breakout_detection import BreakoutDetectionExperiment
from .regime_markov import RegimeMarkovExperiment
from .channel_vol_audit import ChannelVolAuditExperiment
from .risk_director_daily import RiskDirectorDailyExperiment
from .risk_director_scientific_eval import RiskDirectorScientificEvalExperiment
from .risk_director_policy_lab import RiskDirectorPolicyLabExperiment
from .risk_director_temporal_cnn import RiskDirectorTemporalCNNExperiment

ALL_EXPERIMENTS = [
    # A · calidad de dato
    DQPriceControlExperiment,
    DQImpactExperiment,
    DQDailyMonitorExperiment,
    DQSyntheticValidationExperiment,
    DQCapitalImpactExperiment,
    # B · régimen y ruptura
    ChannelVolForecastExperiment,
    BreakoutDetectionExperiment,
    RegimeMarkovExperiment,
    # C · VaR y capital
    PredictedVaRExperiment,
    PortfolioVaRExperiment,
    PortfolioVaRAlertExperiment,
    FRTBCapitalExperiment,
    # D · FRTB (proxies) y auditorías
    FRTBApplicationsExperiment,
    ChannelVolAuditExperiment,
    # E · monitor operativo diario
    RiskDirectorDailyExperiment,
    RiskDirectorScientificEvalExperiment,
    RiskDirectorPolicyLabExperiment,
    RiskDirectorTemporalCNNExperiment,
]

__all__ = [c.__name__ for c in ALL_EXPERIMENTS] + ["ALL_EXPERIMENTS"]
