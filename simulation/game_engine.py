""" 
game_engine.py — BaselineMLB Monte Carlo Game Simulation Engine

Simulates complete MLB games plate-appearance by plate-appearance, tracking all
game state and collecting full probability distributions for every player stat.

Designed to run ~2,500 simulations per game with 60–80 PAs per simulated game.

Imports:
    simulation.config   → SimulationConfig, GameData
    simulation.matchup_model → MatchupModel
"""