"""Train combined Emotion-Attitude-Relationship model routed by exact SFP token.

Features: columns D–K and O of can_enriched.xlsx
  D  num_sfp               – number of SFPs in the sentence
  E  multiple_sfp          – whether sentence has multiple SFPs (0/1)
  F  sfp_distance_end      – distance from SFP to sentence end
  G  sfp_pos               – POS tag of the SFP token
  H  main_pos_pattern      – dominant POS pattern (e.g. noun-sfp, verb-sfp)
  I  negation_present      – negation present (0/1)
  J  sentence_type_guess   – question / statement / emotion / command
  K  emotion_marker_present– explicit emotion word present (0/1)
  O  sfp                   – exact SFP token(s) as written (multi-word kept whole)

Targets (columns L / M / N):
  emotion, attitude, relationship

Strategy: train a global OVR pipeline on all data; additionally train a
per-SFP pipeline for every unique SFP token (col O) that appears ≥ MIN_SFP_SAMPLES
times and has ≥ MIN_SFP_CLASSES distinct combined labels. At predict-time, use
the per-SFP model when available, else fall back to the global model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_CANDIDATES = [
    PROJECT_ROOT / "train" / "can_enriched.xlsx",
    PROJECT_ROOT / "can_enriched.xlsx",
]
MODEL_DIR = PROJECT_ROOT / "backend" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Columns D–K and O (targets L/M/N excluded from features)
FEATURE_COLS: List[str] = [
    "num_sfp",               # D – numeric
    "multiple_sfp",          # E – numeric (0/1)
    "sfp_distance_end",      # F – numeric
    "sfp_pos",               # G – categorical
    "main_pos_pattern",      # H – categorical (e.g. noun-sfp, verb-sfp)
    "negation_present",      # I – numeric (0/1)
    "sentence_type_guess",   # J – categorical
    "emotion_marker_present",# K – numeric (0/1)
    "sfp",                   # O – categorical; multi-word tokens kept whole
]

CATEGORICAL: List[str] = ["sfp_pos", "main_pos_pattern", "sentence_type_guess", "sfp"]
NUMERIC: List[str] = [
    "num_sfp", "multiple_sfp", "sfp_distance_end",
    "negation_present", "emotion_marker_present",
]
TARGET_COLS: List[str] = ["emotion", "attitude", "relationship"]
COMBO_SEP = "|||"

# Minimum rows & distinct labels for a per-SFP sub-model to be trained
MIN_SFP_SAMPLES = 5
MIN_SFP_CLASSES = 2


def find_data_path() -> Path:
    for path in DATA_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("Cannot find can_enriched.xlsx in expected locations")


def normalise_sfp(value: object) -> str:
    """Return the SFP token as-is (stripped). Multi-word SFPs stay whole."""
    token = str(value).strip()
    if not token or token.lower() in ("nan", "none", ""):
        return "__none__"
    return token


def make_combo_label(df: pd.DataFrame) -> pd.Series:
    return (
        df["emotion"].astype(str).str.strip()
        + COMBO_SEP
        + df["attitude"].astype(str).str.strip()
        + COMBO_SEP
        + df["relationship"].astype(str).str.strip()
    )


def split_combo_label(label: str) -> Tuple[str, str, str]:
    parts = str(label).split(COMBO_SEP)
    if len(parts) != 3:
        return str(label), "", ""
    return parts[0], parts[1], parts[2]


def build_ovr_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
            ("num", "passthrough", NUMERIC),
        ]
    )
    clf = OneVsRestClassifier(
        LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            solver="liblinear",
        )
    )
    return Pipeline(steps=[("preprocessor", preprocessor), ("clf", clf)])


@dataclass
class SFPRoutedClassifier:
    """Global OVR + per-SFP OVR heads routed by exact SFP token (col O)."""

    min_sfp_samples: int = MIN_SFP_SAMPLES
    min_sfp_classes: int = MIN_SFP_CLASSES
    global_model: Optional[Pipeline] = None
    sfp_models: Dict[str, Pipeline] = field(default_factory=dict)
    unique_sfps: List[str] = field(default_factory=list)

    def _prep(self, X: pd.DataFrame) -> pd.DataFrame:
        Xc = X[FEATURE_COLS].copy()
        Xc["sfp"] = Xc["sfp"].apply(normalise_sfp)
        return Xc

    def fit(self, X: pd.DataFrame, y_combo: Sequence[str]) -> "SFPRoutedClassifier":
        Xc = self._prep(X)
        y_series = pd.Series(list(y_combo), index=Xc.index)

        # Record all unique SFP tokens seen during training
        self.unique_sfps = sorted(Xc["sfp"].unique().tolist())

        # Global fallback model
        self.global_model = build_ovr_pipeline()
        self.global_model.fit(Xc, y_series)

        # Per-SFP models for tokens with enough data and label diversity
        self.sfp_models = {}
        for sfp_token, grp in Xc.groupby("sfp"):
            if sfp_token == "__none__":
                continue
            y_grp = y_series.loc[grp.index]
            if len(grp) < self.min_sfp_samples:
                continue
            if y_grp.nunique(dropna=True) < self.min_sfp_classes:
                continue
            model = build_ovr_pipeline()
            model.fit(grp, y_grp)
            self.sfp_models[sfp_token] = model

        return self

    def predict(self, X: pd.DataFrame) -> "pd.ndarray":  # type: ignore[type-arg]
        if self.global_model is None:
            raise RuntimeError("Model not fitted. Call fit() first.")

        Xc = self._prep(X)
        preds = pd.Series(index=Xc.index, dtype=object)

        # Route rows that have a dedicated per-SFP model
        for sfp_token, grp in Xc.groupby("sfp"):
            model = self.sfp_models.get(sfp_token)
            if model is not None:
                preds.loc[grp.index] = model.predict(grp)

        # Global model handles everything else
        missing = preds[preds.isna()].index
        if len(missing):
            preds.loc[missing] = self.global_model.predict(Xc.loc[missing])

        return preds.astype(str).values


def component_accuracy(y_true_combo: Sequence[str], y_pred_combo: Sequence[str]) -> Dict[str, float]:
    true_parts = [split_combo_label(x) for x in y_true_combo]
    pred_parts = [split_combo_label(x) for x in y_pred_combo]
    return {
        "emotion":      accuracy_score([t[0] for t in true_parts], [p[0] for p in pred_parts]),
        "attitude":     accuracy_score([t[1] for t in true_parts], [p[1] for p in pred_parts]),
        "relationship": accuracy_score([t[2] for t in true_parts], [p[2] for p in pred_parts]),
    }


def evaluate(df: pd.DataFrame) -> Dict[str, object]:
    work = df.dropna(subset=TARGET_COLS).copy()

    # Ensure sfp col is normalised before splitting
    work["sfp"] = work["sfp"].apply(normalise_sfp)

    X = work[FEATURE_COLS]
    y_combo = make_combo_label(work)

    class_counts = y_combo.value_counts(dropna=False)
    can_stratify = len(class_counts) > 1 and class_counts.min() >= 2

    X_train, X_val, y_train, y_val = train_test_split(
        X, y_combo,
        test_size=0.2,
        random_state=42,
        stratify=y_combo if can_stratify else None,
    )

    # Baseline: single global OVR (no per-SFP routing)
    baseline = build_ovr_pipeline()
    baseline.fit(X_train, y_train)
    baseline_pred = baseline.predict(X_val)

    # Focused: global + per-SFP models
    focused = SFPRoutedClassifier()
    focused.fit(X_train, y_train)
    focused_pred = focused.predict(X_val)

    return {
        "baseline_combo_acc": accuracy_score(y_val, baseline_pred),
        "focused_combo_acc":  accuracy_score(y_val, focused_pred),
        "baseline_comp":      component_accuracy(y_val, baseline_pred),
        "focused_comp":       component_accuracy(y_val, focused_pred),
        "sfp_models_trained": len(focused.sfp_models),
        "unique_sfps":        focused.unique_sfps,
        "sfp_models_list":    sorted(focused.sfp_models.keys()),
    }


def print_sfp_inventory(df: pd.DataFrame) -> None:
    sfp_col = df["sfp"].dropna().apply(normalise_sfp)
    sfp_col = sfp_col[sfp_col != "__none__"]
    counts = sfp_col.value_counts().sort_index()
    print(f"\n=== Unique SFPs in column O ({len(counts)} total) ===")
    for sfp, cnt in counts.items():
        flag = "  [per-SFP model]" if cnt >= MIN_SFP_SAMPLES else ""
        print(f"  {sfp!s:<12} {cnt:>3} rows{flag}")


def main() -> None:
    data_path = find_data_path()
    df = pd.read_excel(data_path)

    # Validate required columns
    required = FEATURE_COLS + TARGET_COLS
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    print(f"Data: {data_path}")
    print(f"Rows: {len(df)}")

    print_sfp_inventory(df)

    metrics = evaluate(df)

    print("\n=== Combined E-A-R Accuracy (20 % holdout) ===")
    print(f"  Baseline  combo-exact: {metrics['baseline_combo_acc'] * 100:.2f}%")
    print(f"  SFP-routed combo-exact:{metrics['focused_combo_acc'] * 100:.2f}%")
    print(f"  Delta:                 {(metrics['focused_combo_acc'] - metrics['baseline_combo_acc']) * 100:+.2f}%")
    print(f"  Per-SFP sub-models:    {metrics['sfp_models_trained']}")
    if metrics["sfp_models_list"]:
        print(f"  SFPs with own model:   {', '.join(metrics['sfp_models_list'])}")

    print("\n  Baseline component accuracy:")
    for k, v in metrics["baseline_comp"].items():
        print(f"    {k:<14}: {v * 100:.2f}%")

    print("\n  SFP-routed component accuracy:")
    for k, v in metrics["focused_comp"].items():
        print(f"    {k:<14}: {v * 100:.2f}%")

    # Retrain on full dataset and persist
    full = df.dropna(subset=TARGET_COLS).copy()
    full["sfp"] = full["sfp"].apply(normalise_sfp)

    final_model = SFPRoutedClassifier()
    final_model.fit(full[FEATURE_COLS], make_combo_label(full))

    model_path = MODEL_DIR / "combined_ear_classifier.pkl"
    joblib.dump(final_model, model_path)

    summary = pd.DataFrame([{
        "baseline_combo_exact":   round(metrics["baseline_combo_acc"] * 100, 2),
        "sfp_routed_combo_exact": round(metrics["focused_combo_acc"] * 100, 2),
        "delta":                  round((metrics["focused_combo_acc"] - metrics["baseline_combo_acc"]) * 100, 2),
        "sfp_models_trained":     metrics["sfp_models_trained"],
        "unique_sfps_total":      len(metrics["unique_sfps"]),
        "baseline_emotion":       round(metrics["baseline_comp"]["emotion"] * 100, 2),
        "baseline_attitude":      round(metrics["baseline_comp"]["attitude"] * 100, 2),
        "baseline_relationship":  round(metrics["baseline_comp"]["relationship"] * 100, 2),
        "sfp_routed_emotion":     round(metrics["focused_comp"]["emotion"] * 100, 2),
        "sfp_routed_attitude":    round(metrics["focused_comp"]["attitude"] * 100, 2),
        "sfp_routed_relationship":round(metrics["focused_comp"]["relationship"] * 100, 2),
    }])
    summary_path = MODEL_DIR / "training_summary_combined.csv"
    summary.to_csv(summary_path, index=False)

    print(f"\nSaved model   : {model_path}")
    print(f"Saved summary : {summary_path}")


if __name__ == "__main__":
    main()
