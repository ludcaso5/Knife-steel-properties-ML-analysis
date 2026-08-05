# Data

This directory contains the data used by the knife-steel analysis.

## Steel Data

The main steel dataset contains:

- steel names;
- toughness ratings;
- edge-retention ratings;
- corrosion-resistance ratings;
- chemical compositions;
- production methods;
- available mean retail prices.

Rows marked as `(predicted)` contain machine-learning estimates. They are
excluded from model training.

The main composition variables are:

```text
C, Cr, Mo, V, W, Co, Ni, Mn, Si, S, P, Cu, Nb, N
```

## Price Data

Price data are collected from:

- Blade HQ;
- KnifeCenter;
- Blades Canada.

The scraping scripts generate product-level observations and average prices by
steel.

Raw webpage caches and scraping checkpoints are not included in the repository.

## Sources

Steel-property ratings are primarily based on:

- Knife Steel Nerds, *Knife Steels Rated by a Metallurgist*;
- Blade HQ, *Knife Steel Guide*.

## Limitations

- The number of observed steels is limited.
- Published ratings are generalized steel-level values.
- Alloy compositions can vary between manufacturers and batches.
- Prices and product availability change over time.
- Predicted values should not be interpreted as laboratory measurements.

## Licensing

The repository's MIT License applies to the original code, not automatically to
third-party ratings, retailer information, or product data.
