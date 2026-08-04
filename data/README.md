# Data Documentation

This directory contains the reference data, prediction candidates, and small
reproducible samples used by the knife-steel machine-learning analysis.

## Directory Structure

```text
data/
│
├── README.md
│
├── raw/
│   ├── steel_data.csv
│   └── steels_to_predict.csv
│
└── sample/
    └── retail_price_sample.csv
```

## Files

### `raw/steel_data.csv`

Reference dataset used for model development and validation.

The current version contains 62 steels and includes:

- steel name;
- toughness rating;
- edge-retention rating;
- corrosion-resistance rating;
- project-specific Global Quality Score;
- percentages for 14 alloying elements;
- production method;
- available mean retail-price observations.

Only rows with non-missing reference target values are eligible for model
training.

### `raw/steels_to_predict.csv`

Candidate steel compositions whose performance properties are estimated by the
trained ensemble models.

The target columns are intentionally empty before prediction:

- `Toughness (avg)`
- `Edge Retention (avg)`
- `Corrosion Resistance (avg)`
- `quality score2`

Predicted rows must never be reintroduced into the training sample as if they
were observed reference values.

### `sample/retail_price_sample.csv`

Small cleaned sample used to reproduce the price-performance analysis without
rerunning the web-collection process.

This file should contain only the fields required for the analysis, such as:

- retailer;
- product name;
- identified steel;
- knife type;
- listed price;
- currency;
- collection date;
- source page identifier or URL, where redistribution is appropriate.

Raw HTML pages, images, complete product descriptions, caches, and request
checkpoints are not included.

## Main Variables

| Column | Description |
|---|---|
| `Steel` | Standardized steel or alloy name |
| `Toughness (avg)` | Published reference toughness rating |
| `Edge Retention (avg)` | Published reference edge-retention rating |
| `Corrosion Resistance (avg)` | Published reference corrosion-resistance rating |
| `quality score2` | Project-specific nonlinear comparative score |
| `C` | Carbon percentage |
| `Cr` | Chromium percentage |
| `Mo` | Molybdenum percentage |
| `V` | Vanadium percentage |
| `W` | Tungsten percentage |
| `Co` | Cobalt percentage |
| `Ni` | Nickel percentage |
| `Mn` | Manganese percentage |
| `Si` | Silicon percentage |
| `S` | Sulfur percentage |
| `P` | Phosphorus percentage |
| `Cu` | Copper percentage |
| `Nb` | Niobium percentage |
| `N` | Nitrogen percentage |
| `Tech` | Production method, such as ingot or powder metallurgy |
| `Mean price` | Available mean retail price for knives using the steel |

Chemical values are expressed as approximate weight percentages.

## Data Provenance

The toughness, edge-retention, and corrosion-resistance reference ratings are
primarily based on:

1. Larrin Thomas, *Knife Steels Rated by a Metallurgist – Toughness, Edge
   Retention, and Corrosion Resistance*, Knife Steel Nerds.
2. George Muhlestein, *Knife Steel Guide*, Blade HQ.

Sources:

- https://knifesteelnerds.com/2021/10/19/knife-steels-rated-by-a-metallurgist-toughness-edge-retention-and-corrosion-resistance/
- https://www.bladehq.com/blog/knife-steel-guide/

Chemical compositions were manually compiled in the original project dataset.
A complete source-by-source provenance table for every composition has not yet
been added. The composition values should therefore be interpreted as
approximate reference values rather than certified batch analyses.

The cleaned price-collection module currently targets publicly accessible
retailer product pages. Additional retailers must be documented here if they
are incorporated into future versions.

## Processing Rules

The modeling pipeline applies the following rules:

1. Rows containing genuine reference ratings may be used for training.
2. Rows identified as model predictions are excluded from training.
3. Missing candidate targets remain missing until prediction.
4. Chemical values are converted to numeric form.
5. Production method is treated as a categorical feature.
6. Derived features are calculated programmatically and are not stored as
   original observations.
7. Model outputs are stored separately from source inputs whenever possible.

## Important Interpretation Notes

The target ratings describe generalized steel-level performance.

They do not directly predict the performance of a particular knife because
actual results can also depend on:

- heat treatment;
- achieved hardness;
- blade and edge geometry;
- sharpening method;
- surface finish;
- manufacturing quality;
- intended use.

The retail-price variables describe complete knives rather than the value of
the steel alone.

## Data Quality Limitations

- The sample size is limited.
- Some values are expert ratings rather than direct measurements.
- Testing procedures are not identical across every steel.
- Alloy compositions may vary within manufacturer specifications.
- Mean prices may be based on different numbers and categories of knives.
- Product availability and retailer prices change over time.
- Some steels occupy regions of the feature space with few comparable
  observations.
- Predictions should not be treated as laboratory-validated material
  properties.

## Licensing and Redistribution

The MIT License in the repository root applies to the original source code, not
automatically to the contents of this directory.

Published ratings, retailer information, product information, and other
third-party material remain subject to the rights and terms of their original
publishers.

This repository includes only the limited processed information needed to
demonstrate and reproduce the analysis. It does not redistribute downloaded
web pages, copyrighted images, complete articles, or full retailer catalogs.
