# ADR 0002: No machine learning; conjugate Bayesian models and Monte Carlo

**Status:** Accepted

## Context
Prediction was requested. Available risk data consists of a handful of
incidents per scenario, control-test samples of 2–60 items, and expert
estimates. The data is small-n, censored and non-stationary, and there is no
labelled outcome to learn from. Risk owners must be able to understand why a
number is what it is.

## Decision
Use Gamma-Poisson (rates), Beta-Binomial (proportions), negative-binomial
predictive distributions with discounting (forecasts), a Poisson GLM
likelihood-ratio test (trends) and Monte Carlo simulation (aggregation). All
are closed-form or standard, and each is validated against known results.

## Alternatives
* Gradient boosting or neural networks for "risk scores": rejected. There is
  no training data or ground truth, they cannot be explained, and they would
  look sophisticated without being defensible.
* Classical point estimates: rejected, because they hide uncertainty.

## Consequences
Forecasts are probabilistic, with intervals and backtests, and they are modest
by design. The project is statistically defensible in front of a risk
committee or an auditor.
