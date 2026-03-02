"""
BaselineMLB Monte Carlo Simulation Engine
==========================================
Core game simulation engine that models full MLB games at the plate-appearance
level, producing probability distributions for player props.

Modules:
    monte_carlo_engine  -- Game simulation with numpy vectorized sampling
    prop_calculator     -- Convert distributions to prop edges and Kelly sizing
    run_daily           -- Daily orchestrator for full slate simulation
"""

__version__ = "1.0.0"
