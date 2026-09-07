# Data

This folder is gitignored — the CSV is ~150 MB and the model artifact is regenerable.

## creditcard.csv

**Source:** Kaggle — Credit Card Fraud Detection (ULB Machine Learning Group)
`https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud`

284,807 transactions from European cardholders, September 2013. 492 are fraud (0.173%).

| Column | Meaning |
|---|---|
| `Time` | Seconds elapsed since the first transaction (not clock time) |
| `V1`–`V28` | PCA components of the original features, anonymised for confidentiality |
| `Amount` | Transaction amount |
| `Class` | 1 = fraud, 0 = normal |

Only `Time`, `Amount` and `Class` are in their original form. The V columns being PCA
output is why they can't be interpreted individually — and, per the Class 4 result, also
why they carry nearly all the usable signal.

Download the CSV and place it here as `data/creditcard.csv`.

## model.joblib

Generated, not downloaded:

```bash
cd ../src
python train_model.py ../data/creditcard.csv
```

Contains the fitted Isolation Forest plus the feature column list and the global
mean/std of `Amount` used for the z-score check. The scoring service loads it once at
startup rather than retraining per request.
