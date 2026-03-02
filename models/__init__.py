"""
models/
=======
XGBoost-based matchup probability models for the BaselineMLB Monte Carlo simulator.

Modules
-------
matchup_model : MatchupModel class -- multiclass XGBoost classifier for plate-appearance outcomes.
train_model   : End-to-end training orchestration script.
predict       : Game-day inference script that produces per-matchup outcome probabilities.
"""
