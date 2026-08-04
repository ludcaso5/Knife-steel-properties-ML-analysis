# Knife-steel-properties-ML-analysis

# Knife Steel Properties: Machine-Learning Analysis

A reproducible Python pipeline for predicting knife-steel toughness,
edge retention, and corrosion resistance from chemical composition and
production method.

The project combines machine-learning validation, target-specific ensemble
models, price-performance analysis, visualization, and experimental
constrained composition optimization.

> **Project status:** The core analysis is implemented. The repository is
> currently being reorganized into a clean and reproducible portfolio project.

## Overview

Knife steels involve important trade-offs between toughness, edge retention,
and corrosion resistance. These properties depend on chemical composition,
production method, heat treatment, hardness, geometry, and other factors.

This project investigates whether published steel-level performance ratings can
be estimated from alloy composition and production method. The resulting models
are also used to compare steels, examine retail price-performance relationships,
and explore candidate compositions under explicit constraints.

The project is intended as a machine-learning and quantitative-analysis case
study. It is not a metallurgical certification tool and does not replace
laboratory testing.

## Research Objectives

1. Estimate toughness, edge retention, and corrosion resistance from alloy
   composition and production method.
2. Compare several regression algorithms using repeated nested
   cross-validation.
3. Construct target-specific ensembles from the best-performing models.
4. measure model disagreement as an indicator of prediction uncertainty.
5. Compare published or predicted steel properties with retail knife prices.
6. Explore constrained candidate compositions while penalizing unrealistic
   and out-of-distribution solutions.

## Dataset

The current reference dataset contains 62 knife steels with:

- published toughness ratings;
- published edge-retention ratings;
- published corrosion-resistance ratings;
- percentages for 14 alloying elements;
- production method, such as ingot or powder metallurgy;
- available mean retail-price observations.

A separate candidate dataset contains steel compositions for which the three
performance properties are estimated by the models.

See [`data/README.md`](data/README.md) for the complete data documentation,
sources, limitations, and licensing notes.

## Input Features

The principal chemical-composition features are:

`C`, `Cr`, `Mo`, `V`, `W`, `Co`, `Ni`, `Mn`, `Si`, `S`, `P`, `Cu`, `Nb`,
and `N`.

The categorical `Tech` variable describes the production method. Additional
engineered features are generated from the original composition variables.

## Prediction Targets

The models estimate three target variables:

- `Toughness (avg)`
- `Edge Retention (avg)`
- `Corrosion Resistance (avg)`

A separate nonlinear Global Quality Score is calculated for comparative
visualization. This score is a project-specific analytical measure and should
not be interpreted as a universal ranking of knife steels.

## Methodology

### Data preparation

The pipeline:

- validates the required columns;
- normalizes column names and numerical formats;
- separates reference observations from prediction candidates;
- excludes previously predicted rows from model training;
- encodes the production method;
- generates composition-based engineered features.

### Candidate models

Five regression approaches are evaluated:

- Ridge Regression
- Kernel Ridge Regression
- Extra Trees
- CatBoost
- Support Vector Regression

### Model validation

Model selection uses repeated nested cross-validation:

- 5 outer folds;
- 10 outer repetitions;
- 5 inner folds for hyperparameter selection;
- RMSE as the principal selection metric;
- additional MAE, R², rank-correlation, and error-threshold diagnostics.

The final predictions use a target-specific ensemble composed of the three
models with the lowest validation RMSE. The selected models are weighted using
inverse RMSE.

### Prediction uncertainty

The project reports disagreement among individual model predictions.

This model disagreement is useful as a relative uncertainty indicator, but it
is not a formally calibrated confidence or prediction interval.

### Experimental optimization

The optional optimization module combines:

- Differential Evolution for global search;
- SLSQP for local refinement;
- chemical-composition bounds;
- maximum total-alloy constraints;
- production-method-specific plausibility penalties;
- distance penalties for compositions far from the training data.

The resulting compositions are computational candidates only. They have not
been validated through thermodynamic simulation, manufacturing, heat treatment,
or laboratory testing.

## Current Validation Results

The following table reports the strongest individual model for each target in
the current repeated nested cross-validation results:

| Target | Best individual model | RMSE | R² |
|---|---:|---:|---:|
| Toughness | Support Vector Regression | 1.431 | 0.611 |
| Edge retention | Ridge Regression | 0.688 | 0.931 |
| Corrosion resistance | Ridge Regression | 0.811 | 0.937 |

These values describe individual models. Final property estimates are produced
by target-specific weighted ensembles.

## Repository Structure

```text
Knife-steel-properties-ML-analysis/
│
├── README.md
├── LICENSE
├── requirements.txt
├── run_pipeline.py
│
├── src/
│   ├── __init__.py
│   ├── data_processing.py
│   ├── train_predict.py
│   ├── scrape_prices.py
│   ├── optimize_composition.py
│   └── generate_results.py
│
├── data/
│   ├── README.md
│   ├── raw/
│   │   ├── steel_data.csv
│   │   └── steels_to_predict.csv
│   └── sample/
│       └── retail_price_sample.csv
│
├── results/
│   ├── figures/
│   ├── metrics/
│   └── tables/
│
├── notebooks/
│   └── project_walkthrough.ipynb
│
└── tests/
```

## Installation

Clone the repository:

```bash
git clone https://github.com/ludcaso5/Knife-steel-properties-ML-analysis.git
cd Knife-steel-properties-ML-analysis
```

Create and activate a virtual environment:

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### macOS or Linux

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Usage

Run the main reproducible pipeline:

```bash
python run_pipeline.py
```

Run the individual modules when needed:

```bash
python -m src.train_predict
python -m src.generate_results
```

Run the optional price-collection module:

```bash
python -m src.scrape_prices
```

Run a shorter version of the experimental optimization:

```bash
python -m src.optimize_composition --quick
```

Run the complete optimization:

```bash
python -m src.optimize_composition --full
```

The main pipeline should remain reproducible without rerunning web scraping.
A small cleaned price sample is therefore included in the repository.

## Principal Outputs

The project generates:

- model-validation metrics;
- selected model parameters and ensemble weights;
- predicted steel properties;
- model-disagreement diagnostics;
- observed and predicted performance maps;
- price-versus-quality figures;
- steel-composition tables;
- experimental optimized-composition candidates.

Generated files are stored under `results/`.

## Data Sources

The reference ratings are primarily based on the following published resources:

- [Knife Steels Rated by a Metallurgist – Toughness, Edge Retention, and
  Corrosion Resistance](https://knifesteelnerds.com/2021/10/19/knife-steels-rated-by-a-metallurgist-toughness-edge-retention-and-corrosion-resistance/)
- [Blade HQ Knife Steel Guide](https://www.bladehq.com/blog/knife-steel-guide/)

Retail-price observations are collected from publicly accessible retailer
product pages. Cached HTML pages and complete website copies are not distributed
in this repository.

## Limitations

- The reference dataset is small relative to the number of original and
  engineered features.
- The target values are published steel-level ratings rather than new
  laboratory measurements produced for this project.
- Heat treatment, hardness, blade geometry, edge geometry, sharpening, and
  manufacturing quality can substantially affect the performance of a specific
  knife.
- The ratings originate from heterogeneous tests, estimates, and expert
  assessments.
- Predictions become less reliable for compositions far from the training
  distribution.
- Model disagreement is not a calibrated statistical interval.
- Retail prices describe complete knives and reflect brand, design, country of
  manufacture, retailer positioning, and other factors beyond steel quality.
- Optimized compositions are model-generated candidates and are not validated
  alloy designs.

## Reproducibility

Randomized procedures use a fixed random seed where applicable. Core input
tables, validation outputs, and a small retail-price sample are retained in the
repository.

Large caches, downloaded HTML pages, virtual environments, temporary files, and
local checkpoints are excluded.

## License

The source code in this repository is licensed under the MIT License.

The datasets, published ratings, retailer information, product information, and
other third-party content are not covered by the MIT License and remain subject
to their original terms and copyrights. See [`data/README.md`](data/README.md).

## Author

**Ludwig Casaubon**

M.Sc. Candidate in Financial Engineering  
HEC Montréal

[LinkedIn](https://www.linkedin.com/in/ludwig-casaubon-461089327/)
