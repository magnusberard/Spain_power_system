import numpy as np
import warnings
from statsmodels.tsa.statespace.sarimax import SARIMAX
from typing import Tuple


class SARIMAXLeadModel:
    """
    Fit one SARIMAX model per lead time using the same exogenous feature set.

    Exogenous features are the flattened past sequence plus flattened future
    known data (same construction as ARX). Each lead uses its own target.
    """

    def __init__(
        self,
        order: Tuple[int, int, int] = (1, 0, 0),
        seasonal_order: Tuple[int, int, int, int] = (0, 0, 0, 0),
        trend: str | None = None,
        maxiter: int = 200,
        disp: bool = False,
        verbose: bool = False,
    ) -> None:
        self.order = order
        self.seasonal_order = seasonal_order
        self.trend = trend
        self.maxiter = maxiter
        self.disp = disp
        self.verbose = verbose
        # Store (fitted_results, train_length) per lead index starting at 1
        self.models: dict[int, tuple] = {}
        self.convergence_info: dict[int, dict] = {}

    def _combine_features(self, X_seq: np.ndarray, X_future: np.ndarray) -> np.ndarray:
        X_seq_flat = X_seq.reshape(X_seq.shape[0], -1)
        X_future_flat = X_future.reshape(X_future.shape[0], -1)
        return np.hstack([X_seq_flat, X_future_flat])

    def fit(self, X_seq_train: np.ndarray, X_future_train: np.ndarray, y_train: np.ndarray) -> None:
        exog_train = self._combine_features(X_seq_train, X_future_train)
        n_samples, n_lead_time = y_train.shape

        for lead in range(n_lead_time):
            endog = y_train[:, lead]
            model = SARIMAX(
                endog=endog,
                exog=exog_train,
                order=self.order,
                seasonal_order=self.seasonal_order,
                trend=self.trend,
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*Maximum Likelihood optimization failed.*")
                results = model.fit(disp=self.disp, maxiter=self.maxiter)
            
            self.models[lead + 1] = (results, n_samples)
            
            # Capture convergence diagnostics
            converged = results.mle_retvals.get("converged", None) if results.mle_retvals else None
            iterations = results.mle_retvals.get("iterations", "n/a") if results.mle_retvals else "n/a"
            self.convergence_info[lead + 1] = {
                "converged": converged,
                "iterations": iterations,
                "aic": results.aic,
                "bic": results.bic,
            }
            
            if self.verbose:
                status = "OK" if converged else "WARN"
                print(f"Lead {lead + 1}: {status} iterations={iterations}, AIC={results.aic:.2f}")

    def predict(self, X_seq_test: np.ndarray, X_future_test: np.ndarray) -> np.ndarray:
        if not self.models:
            raise RuntimeError("Model not fitted. Call fit() first.")

        exog_test = self._combine_features(X_seq_test, X_future_test)
        n_test = exog_test.shape[0]
        n_lead_time = len(self.models)
        predictions = np.zeros((n_test, n_lead_time))

        for lead, (results, train_len) in self.models.items():
            preds = results.predict(
                start=train_len,
                end=train_len + n_test - 1,
                exog=exog_test,
            )
            predictions[:, lead - 1] = preds

        return predictions


def train_sarimax(
    X_seq_train: np.ndarray,
    X_future_train: np.ndarray,
    y_train: np.ndarray,
    order: Tuple[int, int, int] = (1, 0, 0),
    seasonal_order: Tuple[int, int, int, int] = (0, 0, 0, 0),
    trend: str | None = None,
    maxiter: int = 200,
    disp: bool = False,
    verbose: bool = False,
    **kwargs,
):
    """
    Train one SARIMAX per lead time using shared exogenous features.

    Parameters mirror statsmodels.SARIMAX where relevant.
    Extra kwargs are ignored for forward compatibility.
    
    Convergence notes:
    - Set maxiter higher (200+) if convergence warnings appear
    - Try simpler orders (e.g., (0,0,0) seasonal) if still failing
    - Use verbose=True to inspect iterations and diagnostics per lead time
    """
    model = SARIMAXLeadModel(
        order=order,
        seasonal_order=seasonal_order,
        trend=trend,
        maxiter=maxiter,
        disp=disp,
        verbose=verbose,
    )
    model.fit(X_seq_train, X_future_train, y_train)
    return model
