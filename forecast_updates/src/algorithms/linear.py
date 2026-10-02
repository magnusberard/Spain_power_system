import numpy as np
from sklearn.linear_model import LinearRegression
from typing import Iterable


class LinearMultiStepModel:
    """
    Multi-output linear regression over concatenated past and future features.

    Fits a single LinearRegression on flattened past sequences and future
    known features to predict all lead times at once.
    
    This class matches the ForecastingModel interface with train/predict methods.
    """

    def __init__(self, verbose: bool = False, **regressor_kwargs):
        self.verbose = verbose
        self.model = LinearRegression(**regressor_kwargs)

    def _combine_features(self, X_seq: np.ndarray | None, X_future: np.ndarray) -> np.ndarray:
        X_future_flat = X_future.reshape(X_future.shape[0], -1)
        if X_seq is None:
            return X_future_flat
        X_seq_flat = X_seq.reshape(X_seq.shape[0], -1)
        return np.hstack([X_seq_flat, X_future_flat])

    def fit(self, X_seq_train: np.ndarray | None, X_future_train: np.ndarray, y_train: np.ndarray) -> None:
        X_train = self._combine_features(X_seq_train, X_future_train)
        # Handle both 1D and 2D targets
        if y_train.ndim == 1:
            y_train_fit = y_train.reshape(-1, 1)
        else:
            y_train_fit = y_train
        self.model.fit(X_train, y_train_fit)
        if self.verbose:
            r2_score = self.model.score(X_train, y_train_fit)
            print(f"Linear multi-step train R²: {r2_score:.4f}")

    def train(self, X_seq_train: np.ndarray | None, X_future_train: np.ndarray, y_train: np.ndarray, 
              verbose: bool = False, **kwargs) -> None:
        """Train method matching ForecastingModel interface."""
        self.verbose = verbose
        self.fit(X_seq_train, X_future_train, y_train)

    def predict(self, X_seq_test: np.ndarray | None, X_future_test: np.ndarray) -> np.ndarray:
        """Predict method matching ForecastingModel interface."""
        X_test = self._combine_features(X_seq_test, X_future_test)
        return self.model.predict(X_test)


def train_linear(
    X_seq_train: np.ndarray,
    X_future_train: np.ndarray,
    y_train: np.ndarray,
    fit_intercept: bool = True,
    copy_X: bool = True,
    n_jobs: int | None = None,
    positive: bool = False,
    verbose: bool = False,
    **regressor_kwargs,
):
    """
    Train and return a multi-output linear regression model.

    Args mirror sklearn.linear_model.LinearRegression where applicable.
    Unused extra params are ignored when verbose=False (logged otherwise).
    """
    allowed_keys = {"fit_intercept", "copy_X", "n_jobs", "positive"}
    unused_keys = set(regressor_kwargs).difference(allowed_keys)
    if unused_keys and verbose:
        print(f"Ignoring unsupported linear params: {sorted(unused_keys)}")

    lr_kwargs = {
        "fit_intercept": fit_intercept,
        "copy_X": copy_X,
        "n_jobs": n_jobs,
        "positive": positive,
    }

    model = LinearMultiStepModel(verbose=verbose, **lr_kwargs)
    model.fit(X_seq_train, X_future_train, y_train)
    return model

def predict_linear(model: LinearMultiStepModel, X_seq_test: np.ndarray, X_future_test: np.ndarray) -> np.ndarray:
    return model.predict([X_seq_test, X_future_test])