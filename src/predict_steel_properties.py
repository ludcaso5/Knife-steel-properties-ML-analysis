from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hashlib
import os

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from joblib import dump, load
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Ridge
from sklearn.metrics import make_scorer, mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, KFold, RandomizedSearchCV, RepeatedKFold
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVR


# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / ".cache"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Single persistent workbook used as both input and output.
# Observed rows train the models; rows marked "(predicted)" are refreshed.
MASTER_FILE = DATA_DIR / "steel_model_results.xlsx"

BASE_FILE = MASTER_FILE
OUTPUT_FILE = MASTER_FILE

ADD_PREDICTED_SUFFIX = True
RECOMPUTE_BASE_QUALITY_SCORE = True
TRAIN_ON_PREDICTED_ROWS = False
TOP_K_MODELS_PER_TARGET = 3

RUN_GRID_SEARCH = True
USE_RANDOMIZED_SEARCH = True

RANDOM_SEARCH_ITER = 8
FINAL_CV_SPLITS = 5
INNER_CV_SPLITS = 4
OUTER_CV_SPLITS = 5
OUTER_CV_REPEATS = 3

CPU_COUNT = os.cpu_count() or 4
GRID_SEARCH_N_JOBS = max(1, min(6, CPU_COUNT - 2))
CATBOOST_THREADS = max(1, min(6, CPU_COUNT - 2))
SEARCH_PRE_DISPATCH = GRID_SEARCH_N_JOBS

USE_MODEL_CACHE = True
FORCE_RETRAIN = False
MODEL_CACHE_VERSION = 1
MODEL_CACHE_FILE = CACHE_DIR / "steel_ml_model_cache.joblib"

MIMIC_FINAL_POSTPROCESSING_IN_VALIDATION = True

APPLY_METALLURGICAL_CONSTRAINTS = True
ROUND_FINAL_SCORES_TO_HALF = True

RANDOM_STATE = 42
EPSILON = 1e-8
QUALITY_SCORE_EPSILON = 1e-4

# Columns
BASE_FEATURE_COLS = [
    "C", "Cr", "Mo", "V", "W", "Co", "Ni", "Mn", "Si", "S", "P",
    "Cu", "Nb", "N", "Tech",
]

OPTIONAL_FEATURE_COLS = [
    "HRC", "HRC_min", "HRC_max", "HRC_mid",
]

TARGET_COLS = [
    "Toughness (avg)",
    "Edge Retention (avg)",
    "Corrosion Resistance (avg)",
]

OUTPUT_COLS = [
    "Steel",
    "Toughness (avg)",
    "Edge Retention (avg)",
    "Corrosion Resistance (avg)",
    "quality score2",
    "C", "Cr", "Mo", "V", "W", "Co", "Ni", "Mn", "Si", "S", "P",
    "Cu", "Nb", "N",
    "Tech",
    "Mean price",
]

# Main models used in the final ensemble.
MODEL_NAMES = ["ridge", "kernel_ridge", "extratrees", "catboost", "svm"]

ENGINEERED_NUMERIC_COLS = [
    "C_plus_N",
    "hard_carbide_sum",
    "carbide_former_sum",
    "corrosion_proxy",
    "Cr_minus_10C",
    "Cr_to_C",
    "Mo_plus_N",
    "V_Nb_sum",
    "W_Mo_sum",
    "C_times_hard_carbides",
    "C_times_carbide_formers",
    "PM_binary",
    "Ingot_binary",
    "PM_hard_carbide_interaction",
    "Ingot_hard_carbide_interaction",
    "high_carbon_binary",
    "stainless_binary_proxy",
]

# Utility classes
class CatBoostMultiOutputRegressor(BaseEstimator, RegressorMixin):
    """Small sklearn-compatible multi-output wrapper around CatBoostRegressor.

    CatBoost handles categorical features directly; this wrapper fits one model
    per target and lets GridSearchCV tune the shared CatBoost hyperparameters.
    """

    def __init__(
        self,
        iterations: int = 150,
        learning_rate: float = 0.05,
        depth: int = 3,
        l2_leaf_reg: float = 3.0,
        random_seed: int = RANDOM_STATE,
        thread_count: int = CATBOOST_THREADS,
        verbose: bool = False,
    ):
        self.iterations = iterations
        self.learning_rate = learning_rate
        self.depth = depth
        self.l2_leaf_reg = l2_leaf_reg
        self.random_seed = random_seed
        self.thread_count = thread_count
        self.verbose = verbose

    def fit(self, X: pd.DataFrame, y: pd.DataFrame | np.ndarray):
        if not isinstance(X, pd.DataFrame):
            raise TypeError("CatBoostMultiOutputRegressor expects a pandas DataFrame input.")

        if isinstance(y, pd.DataFrame):
            y_df = y.copy()
            self.target_names_ = list(y_df.columns)
        else:
            y_arr = np.asarray(y, dtype=float)
            self.target_names_ = TARGET_COLS[: y_arr.shape[1]]
            y_df = pd.DataFrame(y_arr, columns=self.target_names_)

        cat_features = []
        if "Tech" in X.columns:
            cat_features = [X.columns.get_loc("Tech")]

        params = dict(
            iterations=self.iterations,
            learning_rate=self.learning_rate,
            depth=self.depth,
            l2_leaf_reg=self.l2_leaf_reg,
            loss_function="RMSE",
            eval_metric="RMSE",
            verbose=self.verbose,
            random_seed=self.random_seed,
            allow_writing_files=False,
            thread_count=self.thread_count,
        )

        self.models_ = {}
        for target in self.target_names_:
            model = CatBoostRegressor(**params)
            model.fit(X, y_df[target], cat_features=cat_features)
            self.models_[target] = model
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not isinstance(X, pd.DataFrame):
            raise TypeError("CatBoostMultiOutputRegressor expects a pandas DataFrame input.")
        preds = [self.models_[target].predict(X) for target in self.target_names_]
        return np.vstack(preds).T


@dataclass
class ModelSpec:
    name: str
    estimator: Any
    param_grid: dict[str, list[Any]]
    uses_raw_dataframe: bool = False


# IO helpers

def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=0)
    return pd.read_csv(path, sep=";")


def normalize_tech(series: pd.Series) -> pd.Series:
    out = series.fillna("Other").astype(str).str.strip()
    out = out.mask(out.str.lower().isin(["", "nan", "none"]), "Other")
    return out


def is_predicted_steel(series: pd.Series) -> pd.Series:
    return series.astype(str).str.contains(r"\(predicted\)", case=False, regex=True, na=False)


def clean_steel_name(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace("(predicted)", "", regex=False)
        .str.replace("(Predicted)", "", regex=False)
        .str.strip()
    )


def validate_columns(df: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {label}: {missing}\nAvailable columns: {list(df.columns)}")


def coerce_numeric_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def ensure_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in OUTPUT_COLS:
        if col not in out.columns:
            out[col] = np.nan
    return out


def load_base_data(path: Path) -> pd.DataFrame:
    df = read_table(path)

    df = df.dropna(subset=["Steel"]).reset_index(drop=True)

    validate_columns(df, OUTPUT_COLS, "base file")

    keep_cols = OUTPUT_COLS + [c for c in OPTIONAL_FEATURE_COLS if c in df.columns]
    df = df[keep_cols].copy()
    df["Tech"] = normalize_tech(df["Tech"])
    numeric_cols = [c for c in keep_cols if c not in ["Steel", "Tech"]]
    df = coerce_numeric_columns(df, numeric_cols)
    return df


def load_training_data(base_df: pd.DataFrame) -> pd.DataFrame:
    required = BASE_FEATURE_COLS + TARGET_COLS
    validate_columns(base_df, required, "training data")

    train_source = base_df.copy()
    if not TRAIN_ON_PREDICTED_ROWS:
        train_source = train_source.loc[~is_predicted_steel(train_source["Steel"])].copy()

    required_plus_optional = required + [c for c in OPTIONAL_FEATURE_COLS if c in train_source.columns]
    train_df = train_source[required_plus_optional].copy()
    train_df["Tech"] = normalize_tech(train_df["Tech"])
    train_df = coerce_numeric_columns(train_df, [c for c in required_plus_optional if c != "Tech"])
    train_df = train_df.dropna(subset=TARGET_COLS).reset_index(drop=True)

    if len(train_df) < 10:
        raise ValueError("Training set too small after excluding predicted rows.")

    return train_df


def load_prediction_data(base_df: pd.DataFrame) -> pd.DataFrame:
    predicted_mask = is_predicted_steel(base_df["Steel"])

    if not predicted_mask.any():
        raise ValueError(
            f'No row marked "(predicted)" was found in '
            f'the first worksheet of {MASTER_FILE.name}. '
            'Add new compositions directly to that worksheet and append '
            '"(predicted)" to the steel name.'
        )

    pred_df = base_df.loc[predicted_mask].copy()
    pred_df["Steel"] = clean_steel_name(pred_df["Steel"])

    for target in TARGET_COLS + ["quality score2"]:
        pred_df[target] = np.nan

    return pred_df.reset_index(drop=True)


# Feature engineering
def add_engineered_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Tech"] = normalize_tech(out["Tech"])

    for col in [c for c in BASE_FEATURE_COLS if c != "Tech"] + OPTIONAL_FEATURE_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = np.nan

    chem = {col: out[col].fillna(0.0).astype(float) for col in BASE_FEATURE_COLS if col != "Tech"}
    c = chem["C"]
    cr = chem["Cr"]
    mo = chem["Mo"]
    v = chem["V"]
    w = chem["W"]
    nb = chem["Nb"]
    n = chem["N"]

    tech_lower = out["Tech"].astype(str).str.lower()
    pm_binary = tech_lower.str.contains("pm|powder|sprayform|esr", regex=True).astype(float)
    ingot_binary = tech_lower.str.contains("ingot").astype(float)

    hard_carbide_sum = v + nb + w
    carbide_former_sum = v + nb + w + mo + cr

    out["C_plus_N"] = c + n
    out["hard_carbide_sum"] = hard_carbide_sum
    out["carbide_former_sum"] = carbide_former_sum
    out["corrosion_proxy"] = cr + 3.3 * mo + 16.0 * n
    out["Cr_minus_10C"] = cr - 10.0 * c
    out["Cr_to_C"] = cr / (c + EPSILON)
    out["Mo_plus_N"] = mo + n
    out["V_Nb_sum"] = v + nb
    out["W_Mo_sum"] = w + mo
    out["C_times_hard_carbides"] = c * hard_carbide_sum
    out["C_times_carbide_formers"] = c * carbide_former_sum
    out["PM_binary"] = pm_binary
    out["Ingot_binary"] = ingot_binary
    out["PM_hard_carbide_interaction"] = pm_binary * hard_carbide_sum
    out["Ingot_hard_carbide_interaction"] = ingot_binary * hard_carbide_sum
    out["high_carbon_binary"] = (c >= 1.2).astype(float)
    out["stainless_binary_proxy"] = ((cr >= 10.0) | ((cr + 3.3 * mo + 16.0 * n) >= 12.0)).astype(float)

    if "HRC_mid" not in out.columns or out["HRC_mid"].isna().all():
        if "HRC_min" in out.columns and "HRC_max" in out.columns:
            out["HRC_mid"] = out[["HRC_min", "HRC_max"]].mean(axis=1)
        elif "HRC" in out.columns:
            out["HRC_mid"] = out["HRC"]

    return out


def model_feature_cols(df: pd.DataFrame) -> list[str]:
    optional_available = [c for c in OPTIONAL_FEATURE_COLS if c in df.columns and not df[c].isna().all()]
    if "HRC_mid" in df.columns and not df["HRC_mid"].isna().all() and "HRC_mid" not in optional_available:
        optional_available.append("HRC_mid")
    return BASE_FEATURE_COLS + optional_available + ENGINEERED_NUMERIC_COLS


# Score helpers
def round_to_nearest_half_array(x):
    return np.round(np.asarray(x, dtype=float) * 2.0) / 2.0

def clip_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Toughness (avg)"] = out["Toughness (avg)"].clip(lower=0.5, upper=12.0)
    out["Edge Retention (avg)"] = out["Edge Retention (avg)"].clip(lower=0.5, upper=12.0)
    out["Corrosion Resistance (avg)"] = out["Corrosion Resistance (avg)"].clip(lower=0.0, upper=10.0)
    return out


def compute_quality_score_row(row: pd.Series) -> float:
    toughness = max(float(row["Toughness (avg)"]), EPSILON)
    edge = max(float(row["Edge Retention (avg)"]), EPSILON)
    corrosion = float(row["Corrosion Resistance (avg)"])
    safe_corrosion = max(corrosion, QUALITY_SCORE_EPSILON)
    return (
        np.log(toughness) * 0.84
        + np.log(edge) * 1.55
        + corrosion / 10.0
        + np.log((toughness * edge) ** 0.5)
        + np.log((toughness * edge * safe_corrosion) ** 0.3333) / 2.0
    )


def compute_quality_scores(df: pd.DataFrame) -> pd.Series:
    return df.apply(compute_quality_score_row, axis=1)


def apply_metallurgical_constraints(scores: pd.DataFrame, features_df: pd.DataFrame) -> pd.DataFrame:
    if not APPLY_METALLURGICAL_CONSTRAINTS:
        return scores

    out = scores.copy()
    f = add_engineered_features(features_df)

    c = f["C"].fillna(0.0).astype(float)
    cr = f["Cr"].fillna(0.0).astype(float)
    mo = f["Mo"].fillna(0.0).astype(float)
    n = f["N"].fillna(0.0).astype(float)
    v = f["V"].fillna(0.0).astype(float)
    nb = f["Nb"].fillna(0.0).astype(float)
    w = f["W"].fillna(0.0).astype(float)
    tech = f["Tech"].astype(str).str.lower()

    hard_carbides = v + nb + w
    very_high_hard_carbides = hard_carbides >= 6.0
    high_carbon = c >= 1.4
    pm = tech.str.contains("pm|powder|sprayform|esr", regex=True)

    # Corrosion bounds: low Cr/N/Mo steels should not become stainless-like.
    low_stainless_potential = (cr < 10.0) & (mo < 1.0) & (n < 0.08)
    very_low_stainless_potential = (cr < 5.0) & (mo < 0.75) & (n < 0.05)
    out.loc[low_stainless_potential, "Corrosion Resistance (avg)"] = np.minimum(
        out.loc[low_stainless_potential, "Corrosion Resistance (avg)"], 6.0
    )
    out.loc[very_low_stainless_potential, "Corrosion Resistance (avg)"] = np.minimum(
        out.loc[very_low_stainless_potential, "Corrosion Resistance (avg)"], 4.5
    )

    # High carbon + high chromium but little Mo/N tends to lose free chromium to carbides.
    chromium_carbide_penalty = (cr >= 10.0) & (c >= 1.7) & (mo < 1.0) & (n < 0.05)
    out.loc[chromium_carbide_penalty, "Corrosion Resistance (avg)"] = np.minimum(
        out.loc[chromium_carbide_penalty, "Corrosion Resistance (avg)"], 7.5
    )

    # Toughness bounds: large hard-carbide volume, especially non-PM, should be penalized.
    out.loc[very_high_hard_carbides & high_carbon, "Toughness (avg)"] = np.minimum(
        out.loc[very_high_hard_carbides & high_carbon, "Toughness (avg)"], 6.0
    )
    out.loc[very_high_hard_carbides & high_carbon & ~pm, "Toughness (avg)"] = np.minimum(
        out.loc[very_high_hard_carbides & high_carbon & ~pm, "Toughness (avg)"], 4.5
    )

    # Edge retention: very low C steels should not be predicted as high wear resistance.
    low_carbon = c < 0.55
    out.loc[low_carbon, "Edge Retention (avg)"] = np.minimum(
        out.loc[low_carbon, "Edge Retention (avg)"], 4.0
    )

    # Very high V/Nb content usually implies elevated wear resistance.
    high_v_nb = (v + nb) >= 5.0
    out.loc[high_v_nb, "Edge Retention (avg)"] = np.maximum(
        out.loc[high_v_nb, "Edge Retention (avg)"], 6.0
    )

    return clip_scores(out)


# Preprocessors and models
def dense_one_hot_encoder():
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def build_dense_scaled_preprocessor(feature_cols: list[str]) -> ColumnTransformer:
    numeric_features = [c for c in feature_cols if c != "Tech"]
    numeric_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    categorical_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", dense_one_hot_encoder()),
    ])
    return ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, numeric_features),
            ("cat", categorical_transformer, ["Tech"]),
        ],
        sparse_threshold=0.0,
    )


def build_tree_preprocessor(feature_cols: list[str]) -> ColumnTransformer:
    numeric_features = [c for c in feature_cols if c != "Tech"]
    numeric_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median")),
    ])
    categorical_transformer = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    return ColumnTransformer(transformers=[
        ("num", numeric_transformer, numeric_features),
        ("cat", categorical_transformer, ["Tech"]),
    ])


def avg_rmse_score(y_true, y_pred) -> float:
    y_true_arr = np.asarray(y_true, dtype=float)
    y_pred_arr = np.asarray(y_pred, dtype=float)
    rmse_by_target = np.sqrt(np.mean((y_true_arr - y_pred_arr) ** 2, axis=0))
    return -float(np.mean(rmse_by_target))


NEG_AVG_RMSE_SCORER = make_scorer(avg_rmse_score, greater_is_better=True)


def build_model_specs(feature_cols: list[str]) -> dict[str, ModelSpec]:
    dense_preprocessor = build_dense_scaled_preprocessor(feature_cols)
    tree_preprocessor = build_tree_preprocessor(feature_cols)

    return {
        "ridge": ModelSpec(
            name="ridge",
            estimator=Pipeline(steps=[
                ("preprocess", dense_preprocessor),
                ("model", Ridge()),
            ]),
            param_grid={
                "model__alpha": [0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0],
            },
        ),
        "kernel_ridge": ModelSpec(
            name="kernel_ridge",
            estimator=Pipeline(steps=[
                ("preprocess", dense_preprocessor),
                ("model", KernelRidge(kernel="rbf")),
            ]),
            param_grid={
                "model__alpha": [0.03, 0.1, 0.3, 1.0, 3.0, 10.0],
                "model__gamma": [0.005, 0.01, 0.03, 0.05, 0.10, 0.20],
            },
        ),
        "extratrees": ModelSpec(
            name="extratrees",
            estimator=Pipeline(steps=[
                ("preprocess", tree_preprocessor),
                ("model", ExtraTreesRegressor(random_state=RANDOM_STATE, n_jobs=1)),
            ]),
            param_grid={
                "model__n_estimators": [300, 600],
                "model__max_depth": [3, 5, 8, None],
                "model__min_samples_leaf": [1, 2, 4, 6],
                "model__max_features": [0.5, 0.75, 1.0],
            },
        ),
        "svm": ModelSpec(
            name="svm",
            estimator=Pipeline(steps=[
                ("preprocess", dense_preprocessor),
                ("model", MultiOutputRegressor(SVR(kernel="rbf"))),
            ]),
            param_grid={
                "model__estimator__C": [0.3, 1.0, 3.0, 10.0, 30.0],
                "model__estimator__epsilon": [0.05, 0.10, 0.25, 0.50],
                "model__estimator__gamma": ["scale", 0.01, 0.03, 0.05, 0.10],
            },
        ),
        "catboost": ModelSpec(
            name="catboost",
            estimator=CatBoostMultiOutputRegressor(
                random_seed=RANDOM_STATE,
                thread_count=CATBOOST_THREADS,
            ),
            param_grid={
                "iterations": [80, 150, 250],
                "depth": [2, 3],
                "learning_rate": [0.03, 0.06, 0.10],
                "l2_leaf_reg": [3.0, 8.0, 15.0],
            },
            uses_raw_dataframe=True,
        ),
    }


def count_param_grid_candidates(param_grid: dict[str, list[Any]]) -> int:
    total = 1
    for values in param_grid.values():
        total *= max(1, len(values))
    return int(total)


def fit_search_for_model(
    spec: ModelSpec,
    X: pd.DataFrame,
    y: pd.DataFrame,
    cv,
    random_state: int,
):
    """Tune one model on the supplied training fold only."""
    if not RUN_GRID_SEARCH:
        model = clone(spec.estimator)
        model.fit(X, y)
        return model, {}, np.nan

    n_jobs = 1 if spec.uses_raw_dataframe or spec.name == "catboost" else GRID_SEARCH_N_JOBS

    if USE_RANDOMIZED_SEARCH:
        n_iter = min(RANDOM_SEARCH_ITER, count_param_grid_candidates(spec.param_grid))
        search = RandomizedSearchCV(
            estimator=spec.estimator,
            param_distributions=spec.param_grid,
            n_iter=n_iter,
            scoring=NEG_AVG_RMSE_SCORER,
            cv=cv,
            n_jobs=n_jobs,
            pre_dispatch=SEARCH_PRE_DISPATCH if n_jobs != 1 else 1,
            refit=True,
            random_state=random_state,
            error_score="raise",
        )
    else:
        search = GridSearchCV(
            estimator=spec.estimator,
            param_grid=spec.param_grid,
            scoring=NEG_AVG_RMSE_SCORER,
            cv=cv,
            n_jobs=n_jobs,
            pre_dispatch=SEARCH_PRE_DISPATCH if n_jobs != 1 else 1,
            refit=True,
            error_score="raise",
        )

    search.fit(X, y)
    best_model = search.best_estimator_
    best_params = search.best_params_
    best_cv_avg_rmse = -float(search.best_score_)
    return best_model, best_params, best_cv_avg_rmse


def grid_search_best_models(train_df: pd.DataFrame, feature_cols: list[str]) -> tuple[dict[str, Any], pd.DataFrame]:
    """Final all-data tuning used only to train models for prediction rows."""
    X = train_df[feature_cols].copy()
    y = train_df[TARGET_COLS].copy()

    cv = KFold(n_splits=min(FINAL_CV_SPLITS, len(train_df)), shuffle=True, random_state=RANDOM_STATE)
    specs = build_model_specs(feature_cols)
    best_models: dict[str, Any] = {}
    grid_rows = []

    for model_name in MODEL_NAMES:
        spec = specs[model_name]
        search_label = "RandomizedSearchCV" if USE_RANDOMIZED_SEARCH else "GridSearchCV"
        print(f"\nFinal tuning with {search_label}: {model_name}", flush=True)

        best_model, best_params, best_cv_avg_rmse = fit_search_for_model(
            spec=spec,
            X=X,
            y=y,
            cv=cv,
            random_state=RANDOM_STATE,
        )

        best_models[model_name] = best_model
        grid_rows.append({
            "model": model_name,
            "final_cv_avg_rmse": best_cv_avg_rmse,
            "best_params": repr(best_params),
        })
        print(f"  final CV avg RMSE: {best_cv_avg_rmse:.4f}", flush=True)
        print(f"  best params: {best_params}", flush=True)

    return best_models, pd.DataFrame(grid_rows)

def predict_all_models(features_df: pd.DataFrame, models: dict[str, Any]) -> dict[str, pd.DataFrame]:
    preds = {}
    for model_name, model in models.items():
        pred = model.predict(features_df)
        preds[model_name] = pd.DataFrame(pred, columns=TARGET_COLS, index=features_df.index)
    return preds


def postprocess_score_predictions(pred: np.ndarray, feature_rows: pd.DataFrame, *, round_scores: bool) -> pd.DataFrame:
    pred_df = pd.DataFrame(pred, columns=TARGET_COLS, index=feature_rows.index)
    pred_df = clip_scores(pred_df)
    pred_df = apply_metallurgical_constraints(pred_df, feature_rows)

    if round_scores:
        pred_df = pred_df.apply(round_to_nearest_half_array)
        pred_df = clip_scores(pred_df)
        pred_df = apply_metallurgical_constraints(pred_df, feature_rows)

    return pred_df


def summarize_oof_predictions(
    y_true: pd.DataFrame,
    oof_preds: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rmse_table = pd.DataFrame(index=MODEL_NAMES, columns=TARGET_COLS, dtype=float)
    metric_rows = []

    for model_name, pred_df in oof_preds.items():
        for target in TARGET_COLS:
            yt = y_true[target].astype(float)
            yp = pred_df[target].astype(float)

            rmse = float(np.sqrt(mean_squared_error(yt, yp)))
            mae = float(mean_absolute_error(yt, yp))
            try:
                r2 = float(r2_score(yt, yp))
            except ValueError:
                r2 = np.nan
            spearman = float(pd.Series(yt).corr(pd.Series(yp), method="spearman"))
            hit_05 = float((np.abs(yt.to_numpy() - yp.to_numpy()) <= 0.5).mean())
            hit_10 = float((np.abs(yt.to_numpy() - yp.to_numpy()) <= 1.0).mean())

            rmse_table.loc[model_name, target] = rmse
            metric_rows.append({
                "model": model_name,
                "target": target,
                "rmse": rmse,
                "mae": mae,
                "r2": r2,
                "spearman_rank_corr": spearman,
                "pct_error_le_0_5": hit_05,
                "pct_error_le_1_0": hit_10,
            })

    return rmse_table, pd.DataFrame(metric_rows)


def compute_repeated_nested_validation(train_df: pd.DataFrame, feature_cols: list[str]):
    """Repeated outer CV where hyperparameters are re-tuned inside each train fold.

    This replaces the optimistic pattern "tune once on all data, then validate".
    Each outer test prediction is produced by a model whose hyperparameters were
    selected without seeing that outer test fold.
    """
    X = train_df[feature_cols].copy().reset_index(drop=True)
    y = train_df[TARGET_COLS].copy().reset_index(drop=True)
    specs = build_model_specs(feature_cols)

    outer_cv = RepeatedKFold(
        n_splits=min(OUTER_CV_SPLITS, len(train_df)),
        n_repeats=OUTER_CV_REPEATS,
        random_state=RANDOM_STATE,
    )

    oof_sums = {
        model_name: pd.DataFrame(0.0, index=y.index, columns=TARGET_COLS)
        for model_name in MODEL_NAMES
    }
    oof_counts = {
        model_name: pd.Series(0, index=y.index, dtype=int)
        for model_name in MODEL_NAMES
    }
    fold_rows = []

    n_outer = outer_cv.get_n_splits(X, y)
    for fold_id, (train_idx, test_idx) in enumerate(outer_cv.split(X, y), start=1):
        X_train = X.iloc[train_idx].copy()
        y_train = y.iloc[train_idx].copy()
        X_test = X.iloc[test_idx].copy()
        y_test = y.iloc[test_idx].copy()

        inner_cv = KFold(
            n_splits=min(INNER_CV_SPLITS, len(train_idx)),
            shuffle=True,
            random_state=RANDOM_STATE + fold_id,
        )

        print(f"  nested outer fold {fold_id}/{n_outer} | train={len(train_idx)} test={len(test_idx)}", flush=True)

        for model_name in MODEL_NAMES:
            spec = specs[model_name]
            best_model, best_params, inner_rmse = fit_search_for_model(
                spec=spec,
                X=X_train,
                y=y_train,
                cv=inner_cv,
                random_state=RANDOM_STATE + fold_id,
            )

            raw_pred = best_model.predict(X_test)
            if MIMIC_FINAL_POSTPROCESSING_IN_VALIDATION:
                pred_df = postprocess_score_predictions(
                    raw_pred,
                    X_test,
                    round_scores=ROUND_FINAL_SCORES_TO_HALF,
                )
            else:
                pred_df = pd.DataFrame(raw_pred, columns=TARGET_COLS, index=X_test.index)

            oof_sums[model_name].loc[test_idx, TARGET_COLS] += pred_df[TARGET_COLS].to_numpy()
            oof_counts[model_name].loc[test_idx] += 1

            for target in TARGET_COLS:
                fold_rows.append({
                    "fold_id": fold_id,
                    "model": model_name,
                    "target": target,
                    "inner_cv_avg_rmse": inner_rmse,
                    "outer_fold_rmse": float(np.sqrt(mean_squared_error(y_test[target], pred_df[target]))),
                    "outer_fold_mae": float(mean_absolute_error(y_test[target], pred_df[target])),
                    "best_params": repr(best_params),
                })

    oof_preds = {}
    for model_name in MODEL_NAMES:
        counts = oof_counts[model_name].replace(0, np.nan)
        oof_preds[model_name] = oof_sums[model_name].div(counts, axis=0)

    rmse_table, validation_metrics = summarize_oof_predictions(y, oof_preds)
    fold_details = pd.DataFrame(fold_rows)
    return rmse_table, oof_preds, validation_metrics, fold_details


def compute_top_k_weights(rmse_table: pd.DataFrame, top_k: int = TOP_K_MODELS_PER_TARGET) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=rmse_table.index, columns=rmse_table.columns, dtype=float)

    for target in TARGET_COLS:
        top_models = rmse_table[target].astype(float).sort_values(ascending=True).head(top_k).index
        inv_rmse = 1.0 / rmse_table.loc[top_models, target].astype(float).clip(lower=EPSILON)
        weights.loc[top_models, target] = inv_rmse / inv_rmse.sum()

    return weights


def predict_weighted_ensemble_raw(features_df: pd.DataFrame, models: dict[str, Any], weights: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    model_preds = predict_all_models(features_df, models)
    weighted_pred = pd.DataFrame(0.0, index=features_df.index, columns=TARGET_COLS)

    for model_name, pred_df in model_preds.items():
        for target in TARGET_COLS:
            weight = float(weights.loc[model_name, target])
            if weight != 0.0:
                weighted_pred[target] += weight * pred_df[target]

    weighted_pred = clip_scores(weighted_pred)
    weighted_pred = apply_metallurgical_constraints(weighted_pred, features_df)
    return weighted_pred, model_preds


def compute_prediction_uncertainty(model_preds: dict[str, pd.DataFrame], weights: pd.DataFrame) -> pd.DataFrame:
    rows = []
    index = next(iter(model_preds.values())).index

    for idx in index:
        row = {"row_index": idx}
        per_target_stds = []
        for target in TARGET_COLS:
            used_models = weights.index[weights[target] > 0].tolist()
            values = np.asarray([model_preds[m].loc[idx, target] for m in used_models], dtype=float)
            if len(values) > 1:
                std_val = float(np.std(values, ddof=1))
            else:
                std_val = 0.0
            row[f"std_{target}"] = std_val
            row[f"models_used_{target}"] = ", ".join(used_models)
            per_target_stds.append(std_val)
        row["mean_prediction_std"] = float(np.mean(per_target_stds))
        rows.append(row)

    return pd.DataFrame(rows).set_index("row_index")


# Prediction-row filling and combination
def fill_prediction_rows(pred_df: pd.DataFrame, models: dict[str, Any], weights: pd.DataFrame, feature_cols: list[str]):
    out = pred_df.copy().reset_index(drop=True)
    out["Tech"] = normalize_tech(out["Tech"])
    out_features = add_engineered_features(out)

    raw_scores, model_preds = predict_weighted_ensemble_raw(out_features[feature_cols].copy(), models, weights)
    uncertainty = compute_prediction_uncertainty(model_preds, weights)

    final_scores = raw_scores.copy()
    if ROUND_FINAL_SCORES_TO_HALF:
        final_scores = final_scores.apply(round_to_nearest_half_array)
        final_scores = clip_scores(final_scores)
        final_scores = apply_metallurgical_constraints(final_scores, out_features[feature_cols].copy())

    for target in TARGET_COLS:
        out[target] = final_scores[target].to_numpy()

    out["quality score2"] = compute_quality_scores(out)
    out["Mean price"] = np.nan

    detail_rows = []
    for i, steel in enumerate(out["Steel"].astype(str)):
        detail = {"Steel": steel}
        for target in TARGET_COLS:
            detail[f"final_{target}"] = out.loc[i, target]
            detail[f"raw_ensemble_{target}"] = raw_scores.loc[i, target]
            detail[f"std_{target}"] = uncertainty.loc[i, f"std_{target}"]
            detail[f"models_used_{target}"] = uncertainty.loc[i, f"models_used_{target}"]
            for model_name, pred_df_model in model_preds.items():
                detail[f"{model_name}_{target}"] = pred_df_model.loc[i, target]
        detail["mean_prediction_std"] = uncertainty.loc[i, "mean_prediction_std"]
        detail_rows.append(detail)

    detail_df = pd.DataFrame(detail_rows)
    return out[OUTPUT_COLS], detail_df


def make_predicted_names(pred_df: pd.DataFrame) -> pd.DataFrame:
    out = pred_df.copy()
    if not ADD_PREDICTED_SUFFIX:
        return out
    already_tagged = out["Steel"].astype(str).str.contains("predicted", case=False, na=False)
    out.loc[~already_tagged, "Steel"] = out.loc[~already_tagged, "Steel"].astype(str) + " (predicted)"
    return out


def combine_base_and_predicted(base_df: pd.DataFrame, predicted_df: pd.DataFrame):
    base_out = base_df.copy()
    if RECOMPUTE_BASE_QUALITY_SCORE:
        base_out["quality score2"] = compute_quality_scores(base_out)

    observed_base = base_out.loc[~is_predicted_steel(base_out["Steel"])].copy()

    pred_out = predicted_df.copy()
    pred_out = make_predicted_names(pred_out)

    observed_raw_names = clean_steel_name(observed_base["Steel"]).str.upper()
    pred_raw_names = clean_steel_name(pred_out["Steel"]).str.upper()
    duplicate_observed = pred_raw_names.isin(observed_raw_names)
    skipped = pred_out.loc[duplicate_observed, "Steel"].astype(str).tolist()
    pred_out = pred_out.loc[~duplicate_observed].copy()

    combined = pd.concat([observed_base[OUTPUT_COLS], pred_out[OUTPUT_COLS]], ignore_index=True)
    return combined, skipped


# Output writers
def write_results_excel(
    df: pd.DataFrame,
    weights: pd.DataFrame,
    rmse_table: pd.DataFrame,
    validation_metrics: pd.DataFrame,
    fold_details: pd.DataFrame,
    grid_summary: pd.DataFrame,
    prediction_details: pd.DataFrame,
    output_path: Path,
) -> None:
    model_sheet_names = {
        "Results_1",
        "NestedCV_top3_weights",
        "NestedCV_metrics",
        "NestedCV_fold_details",
        "FinalSearch_best_params",
        "Prediction_details",
    }

    preserved_sheets: dict[str, pd.DataFrame] = {}

    if output_path.exists():
        with pd.ExcelFile(output_path) as existing_book:
            current_results_sheet = (
                existing_book.sheet_names[0]
                if existing_book.sheet_names
                else None
            )

            for sheet in existing_book.sheet_names:
                if sheet == current_results_sheet:
                    continue

                if sheet in model_sheet_names:
                    continue

                if sheet.startswith("Optimizer_"):
                    continue

                preserved_sheets[sheet] = pd.read_excel(
                    existing_book,
                    sheet_name=sheet,
                )

    validation_sheet = pd.concat(
        {
            "NestedRepeatedCV_RMSE": rmse_table,
            "Top3_inverse_RMSE_weight": weights,
        },
        axis=1,
    )

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        sheet_name = "Results_1"
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        validation_sheet.to_excel(writer, sheet_name="NestedCV_top3_weights")
        validation_metrics.to_excel(writer, sheet_name="NestedCV_metrics", index=False)
        fold_details.to_excel(writer, sheet_name="NestedCV_fold_details", index=False)
        grid_summary.to_excel(writer, sheet_name="FinalSearch_best_params", index=False)
        prediction_details.to_excel(writer, sheet_name="Prediction_details", index=False)
        for sheet, preserved_df in preserved_sheets.items():
            preserved_df.to_excel(
                writer,
                sheet_name=sheet,
                index=False,
            )

        workbook = writer.book
        header_fmt = workbook.add_format({
            "bold": True,
            "bg_color": "#E8F1FA",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })
        num_fmt = workbook.add_format({"num_format": "0.00"})
        score_fmt = workbook.add_format({"num_format": "0.000000"})
        price_fmt = workbook.add_format({"num_format": "0.00"})
        weight_fmt = workbook.add_format({"num_format": "0.0000"})

        for ws_name, sheet_df in [
            (sheet_name, df),
            ("NestedCV_metrics", validation_metrics),
            ("NestedCV_fold_details", fold_details),
            ("FinalSearch_best_params", grid_summary),
            ("Prediction_details", prediction_details),
        ]:
            worksheet = writer.sheets[ws_name]
            for col_num, col_name in enumerate(sheet_df.columns):
                worksheet.write(0, col_num, col_name, header_fmt)
                series_as_str = sheet_df[col_name].astype(str).replace("nan", "")
                width = max(len(col_name) + 2, min(45, int(series_as_str.str.len().max()) + 2))
                worksheet.set_column(col_num, col_num, width)
            worksheet.freeze_panes(1, 1)
            worksheet.autofilter(0, 0, len(sheet_df), len(sheet_df.columns) - 1)

        worksheet = writer.sheets[sheet_name]
        numeric_cols = TARGET_COLS + ["C", "Cr", "Mo", "V", "W", "Co", "Ni", "Mn", "Si", "S", "P", "Cu", "Nb", "N"]
        for col in numeric_cols:
            if col in df.columns:
                col_idx = df.columns.get_loc(col)
                worksheet.set_column(col_idx, col_idx, 13, num_fmt)
        worksheet.set_column(df.columns.get_loc("quality score2"), df.columns.get_loc("quality score2"), 14, score_fmt)
        worksheet.set_column(df.columns.get_loc("Mean price"), df.columns.get_loc("Mean price"), 12, price_fmt)

        weights_ws = writer.sheets["NestedCV_top3_weights"]
        for col_num in range(validation_sheet.shape[1] + 1):
            weights_ws.set_column(col_num, col_num, 22, weight_fmt)
        weights_ws.freeze_panes(3, 1)

# Persistent fitted-model cache
def build_training_signature(train_df: pd.DataFrame, feature_cols: list[str]) -> str:
    """Hash observed training data plus settings that affect fitted models."""
    signature_cols = feature_cols + TARGET_COLS
    frame = train_df[signature_cols].copy()
    data_bytes = pd.util.hash_pandas_object(
        frame,
        index=True,
    ).to_numpy(dtype=np.uint64).tobytes()

    settings_bytes = repr({
        "cache_version": MODEL_CACHE_VERSION,
        "model_names": MODEL_NAMES,
        "feature_cols": feature_cols,
        "target_cols": TARGET_COLS,
        "run_grid_search": RUN_GRID_SEARCH,
        "use_randomized_search": USE_RANDOMIZED_SEARCH,
        "random_search_iter": RANDOM_SEARCH_ITER,
        "final_cv_splits": FINAL_CV_SPLITS,
        "inner_cv_splits": INNER_CV_SPLITS,
        "outer_cv_splits": OUTER_CV_SPLITS,
        "outer_cv_repeats": OUTER_CV_REPEATS,
        "top_k": TOP_K_MODELS_PER_TARGET,
        "postprocess_validation": MIMIC_FINAL_POSTPROCESSING_IN_VALIDATION,
        "constraints": APPLY_METALLURGICAL_CONSTRAINTS,
        "round_half": ROUND_FINAL_SCORES_TO_HALF,
        "random_state": RANDOM_STATE,
    }).encode("utf-8")

    return hashlib.sha256(data_bytes + settings_bytes).hexdigest()


def load_model_bundle(signature: str, feature_cols: list[str]) -> dict[str, Any] | None:
    if FORCE_RETRAIN or not USE_MODEL_CACHE or not MODEL_CACHE_FILE.exists():
        return None

    try:
        bundle = load(MODEL_CACHE_FILE)
    except Exception as exc:
        print(f"[CACHE] Unable to load cache; retraining: {exc}", flush=True)
        return None

    required_keys = {
        "signature",
        "feature_cols",
        "final_models",
        "weights",
        "rmse_table",
        "validation_metrics",
        "fold_details",
        "grid_summary",
    }
    if not required_keys.issubset(bundle):
        print("[CACHE] Incomplete cache; retraining.", flush=True)
        return None

    if bundle["signature"] != signature:
        print("[CACHE] Training data/settings changed; retraining.", flush=True)
        return None

    if list(bundle["feature_cols"]) != list(feature_cols):
        print("[CACHE] Feature columns changed; retraining.", flush=True)
        return None

    print(f"[CACHE] Reusing fitted models from {MODEL_CACHE_FILE.name}", flush=True)
    return bundle


def save_model_bundle(
    *,
    signature: str,
    feature_cols: list[str],
    final_models: dict[str, Any],
    weights: pd.DataFrame,
    rmse_table: pd.DataFrame,
    validation_metrics: pd.DataFrame,
    fold_details: pd.DataFrame,
    grid_summary: pd.DataFrame,
) -> None:
    if not USE_MODEL_CACHE:
        return

    bundle = {
        "signature": signature,
        "feature_cols": list(feature_cols),
        "final_models": final_models,
        "weights": weights,
        "rmse_table": rmse_table,
        "validation_metrics": validation_metrics,
        "fold_details": fold_details,
        "grid_summary": grid_summary,
    }
    dump(bundle, MODEL_CACHE_FILE, compress=0)
    print(f"[CACHE] Saved fitted models to {MODEL_CACHE_FILE.name}", flush=True)


# Main
def main() -> None:
    print("loading files...", flush=True)
    if not BASE_FILE.exists():
        raise FileNotFoundError(
            f"Master workbook not found: {BASE_FILE}"
        )

    base_file = BASE_FILE
    base_df = load_base_data(base_file)
    pred_df = load_prediction_data(base_df)
    train_df_raw = load_training_data(base_df)
    train_df = add_engineered_features(train_df_raw)
    feature_cols = model_feature_cols(train_df)

    print(f"base file: {base_file}", flush=True)
    print(f"observed training rows: {len(train_df)}", flush=True)
    print(f"prediction rows: {len(pred_df)}", flush=True)
    print(f"feature columns used: {feature_cols}", flush=True)

    signature = build_training_signature(train_df, feature_cols)
    cached_bundle = load_model_bundle(signature, feature_cols)

    if cached_bundle is not None:
        final_models = cached_bundle["final_models"]
        weights = cached_bundle["weights"]
        rmse_table = cached_bundle["rmse_table"]
        validation_metrics = cached_bundle["validation_metrics"]
        fold_details = cached_bundle["fold_details"]
        grid_summary = cached_bundle["grid_summary"]
    else:
        print(
            "\n1) Repeated nested CV validation. Hyperparameters are tuned inside each outer fold.",
            flush=True,
        )
        rmse_table, _, validation_metrics, fold_details = (
            compute_repeated_nested_validation(train_df, feature_cols)
        )
        print("\nNested repeated CV RMSE by model and target:", flush=True)
        print(rmse_table.round(4).to_string(), flush=True)

        print("\nNested repeated CV metrics:", flush=True)
        print(validation_metrics.round(4).to_string(index=False), flush=True)

        weights = compute_top_k_weights(
            rmse_table,
            TOP_K_MODELS_PER_TARGET,
        )
        print(
            f"\nTop {TOP_K_MODELS_PER_TARGET} inverse-RMSE weights used by target:",
            flush=True,
        )
        print(weights.round(4).to_string(), flush=True)

        print(
            "\n2) Final tuning on all observed rows for production predictions.",
            flush=True,
        )
        final_models, grid_summary = grid_search_best_models(
            train_df,
            feature_cols,
        )

        save_model_bundle(
            signature=signature,
            feature_cols=feature_cols,
            final_models=final_models,
            weights=weights,
            rmse_table=rmse_table,
            validation_metrics=validation_metrics,
            fold_details=fold_details,
            grid_summary=grid_summary,
        )

    print("\n3) Re-predicting predicted rows using validation-safe top-3 weighted ensemble.", flush=True)
    predicted_df, prediction_details = fill_prediction_rows(pred_df, final_models, weights, feature_cols)
    combined_df, skipped_duplicates = combine_base_and_predicted(base_df, predicted_df)

    write_results_excel(
        combined_df,
        weights,
        rmse_table,
        validation_metrics,
        fold_details,
        grid_summary,
        prediction_details,
        OUTPUT_FILE,
    )

    if skipped_duplicates:
        print("\nPredicted rows skipped because their base steel already exists as observed:", flush=True)
        print(", ".join(skipped_duplicates), flush=True)

    print(
        f"\nUpdated master workbook: {OUTPUT_FILE}",
        flush=True,
    )

    print("\nPredicted rows added/refreshed:", flush=True)
    added_names = combined_df.iloc[len(combined_df) - len(predicted_df):][["Steel"] + TARGET_COLS + ["quality score2"]]
    print(added_names.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
