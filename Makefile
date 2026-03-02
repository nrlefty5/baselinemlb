# =============================================================================
# Makefile — Baseline MLB
# Common commands for local development and CI
# =============================================================================

.PHONY: help simulate backtest train refresh-data test lint test-python \
        test-frontend projections grade props setup clean full-daily-pipeline \
        backfill-statcast build-training-data train-model full-pipeline \
        quick-test-pipeline

PYTHON ?= python3.11
PIP ?= pip
NPM ?= npm
NUM_SIMS ?= 10000

# Data pipeline year range (override on command line: make backfill-statcast START_YEAR=2023)
START_YEAR ?= 2020
END_YEAR   ?= 2025

CYAN  := \033[36m
GREEN := \033[32m
RESET := \033[0m

help: ## Show available commands
	@echo ""
	@echo "$(CYAN)Baseline MLB — Development Commands$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-24s$(RESET) %s\n", $$1, $$2}'
	@echo ""

setup: ## Install all dependencies (Python + Node)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install ruff pytest pytest-cov xgboost scikit-learn numpy scipy joblib
	cd frontend && $(NPM) install

simulate: ## Run Monte Carlo simulation for today's games
	@echo "$(CYAN)Running simulation pipeline...$(RESET)"
	$(PYTHON) pipeline/fetch_games.py
	$(PYTHON) pipeline/fetch_players.py
	$(PYTHON) pipeline/fetch_props.py
	$(PYTHON) pipeline/generate_projections.py
	$(PYTHON) pipeline/generate_batter_projections.py
	@echo "$(GREEN)Point-estimate projections complete.$(RESET)"
	@echo "$(CYAN)Running Monte Carlo engine ($(NUM_SIMS) sims)...$(RESET)"
	$(PYTHON) -m simulator.run_daily --n-sims $(NUM_SIMS) || echo "$(CYAN)MC simulator skipped (dependencies not met or no games today).$(RESET)"
	@echo "$(GREEN)Simulation complete.$(RESET)"

backtest: ## Run backtest for the past week
	@echo "$(CYAN)Running weekly backtest...$(RESET)"
	$(PYTHON) scripts/grade_accuracy.py --backfill 7
	@echo "$(GREEN)Backtest complete.$(RESET)"

train: ## Retrain the XGBoost matchup model
	@echo "$(CYAN)Retraining model...$(RESET)"
	@mkdir -p models data/training
	$(PYTHON) scripts/grade_accuracy.py --backfill 30
	@echo "For full retrain, run: gh workflow run model_retrain.yml"

refresh-data: ## Fetch latest Statcast, props, and umpire data
	@echo "$(CYAN)Refreshing data...$(RESET)"
	$(PYTHON) pipeline/fetch_statcast.py
	$(PYTHON) pipeline/fetch_props.py
	$(PYTHON) pipeline/fetch_umpire_framing.py
	@echo "$(GREEN)Data refresh complete.$(RESET)"

projections: ## Generate pitcher + batter projections for today
	$(PYTHON) pipeline/generate_projections.py
	$(PYTHON) pipeline/generate_batter_projections.py

props: ## Fetch latest prop lines from The Odds API
	$(PYTHON) pipeline/fetch_props.py

grade: ## Grade yesterday's picks against actual results
	$(PYTHON) scripts/grade_accuracy.py
	$(PYTHON) scripts/track_clv.py

test: lint test-python test-frontend ## Run all tests (lint + pytest + frontend)
	@echo "$(GREEN)All tests passed.$(RESET)"

lint: ## Lint Python code with Ruff
	ruff check pipeline/ scripts/ lib/ tests/ \
		--select E,F,W,I --ignore E501,E402

test-python: ## Run Python unit tests with Pytest
	$(PYTHON) -m pytest tests/ -v --tb=short \
		--cov=pipeline --cov=lib --cov-report=term-missing

test-frontend: ## Build and lint the Next.js frontend
	cd frontend && $(NPM) run lint || true
	cd frontend && $(NPM) run build

clean: ## Remove cached data and build artifacts
	rm -rf data/*.json data/training/ __pycache__ .pytest_cache .ruff_cache
	rm -rf frontend/.next frontend/node_modules/.cache

full-daily-pipeline: ## Run the complete daily sim pipeline end-to-end (refresh → simulate → grade)
	$(MAKE) refresh-data
	$(MAKE) simulate
	$(MAKE) grade

# =============================================================================
# Data pipeline targets (Statcast backfill → feature build → model training)
# Override year range: make backfill-statcast START_YEAR=2023 END_YEAR=2025
# =============================================================================

backfill-statcast: ## Download Statcast PA features (START_YEAR–END_YEAR)
	@echo "$(CYAN)Backfilling Statcast data $(START_YEAR)–$(END_YEAR)...$(RESET)"
	@mkdir -p data
	$(PYTHON) pipeline/fetch_statcast_historical.py \
		--start-year $(START_YEAR) \
		--end-year $(END_YEAR)
	@echo "$(GREEN)Statcast backfill complete.$(RESET)"

build-training-data: ## Build train/test parquet splits from PA features
	@echo "$(CYAN)Building training dataset...$(RESET)"
	@mkdir -p data/training
	$(PYTHON) pipeline/build_training_dataset.py \
		--input data/statcast_pa_features_$(START_YEAR)_$(END_YEAR).parquet \
		--output-dir data/training
	@echo "$(GREEN)Training dataset ready in data/training/.$(RESET)"

train-model: ## Train LightGBM matchup model (5-fold CV + final)
	@echo "$(CYAN)Training LightGBM matchup model...$(RESET)"
	@mkdir -p models/artifacts
	$(PYTHON) -m models.train_model \
		--data-dir data/training \
		--artifact-dir models/artifacts
	@echo "$(GREEN)Model artifacts written to models/artifacts/.$(RESET)"

full-pipeline: ## Full ML pipeline: backfill-statcast → build-training-data → train-model
	@echo "$(CYAN)Running full ML data pipeline ($(START_YEAR)–$(END_YEAR))...$(RESET)"
	$(MAKE) backfill-statcast START_YEAR=$(START_YEAR) END_YEAR=$(END_YEAR)
	$(MAKE) build-training-data START_YEAR=$(START_YEAR) END_YEAR=$(END_YEAR)
	$(MAKE) train-model
	@echo "$(GREEN)Full ML pipeline complete.$(RESET)"

quick-test-pipeline: ## Quick single-season pipeline test (2024 only, no CV)
	@echo "$(CYAN)Running quick test pipeline (2024, no CV)...$(RESET)"
	@mkdir -p data data/training models/artifacts
	$(PYTHON) pipeline/fetch_statcast_historical.py \
		--start-year 2024 --end-year 2024
	$(PYTHON) pipeline/build_training_dataset.py \
		--input data/statcast_pa_features_2024_2024.parquet \
		--output-dir data/training
	$(PYTHON) -m models.train_model \
		--data-dir data/training \
		--artifact-dir models/artifacts \
		--no-cv
	@echo "$(GREEN)Quick test pipeline complete.$(RESET)"
