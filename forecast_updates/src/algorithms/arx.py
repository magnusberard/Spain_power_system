import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression


def plot_arx_residuals(
    y_true,
    y_pred,
    lead_time: int | None = None,
    bins: int = 30,
    figsize: tuple[int, int] = (12, 5),
):
    """Plot ARX residuals as a time series and histogram.

    Residuals are computed as ``y_true - y_pred``. Inputs can be 1-D arrays,
    2-D arrays with shape ``(n_samples, n_lead_times)``, or pandas objects
    convertible to numpy arrays.

    Args:
        y_true: Ground-truth values.
        y_pred: Predicted values.
        lead_time: 1-based lead time to plot when inputs are 2-D. If ``None``
            and 2-D input is provided, the residuals are averaged over lead times.
        bins: Number of bins in the residual histogram.
        figsize: Figure size passed to matplotlib.

    Returns:
        numpy.ndarray: The 1-D residual array that was plotted.
    """
    y_true_arr = np.asarray(y_true)
    y_pred_arr = np.asarray(y_pred)

    if y_true_arr.shape != y_pred_arr.shape:
        raise ValueError(
            "y_true and y_pred must have the same shape. "
            f"Got {y_true_arr.shape} and {y_pred_arr.shape}."
        )

    if y_true_arr.ndim == 1:
        residuals = y_true_arr - y_pred_arr
        plot_label = "Residual"
    elif y_true_arr.ndim == 2:
        if lead_time is None:
            residuals = (y_true_arr - y_pred_arr).mean(axis=1)
            plot_label = "Residual (mean over lead times)"
        else:
            if lead_time < 1 or lead_time > y_true_arr.shape[1]:
                raise ValueError(
                    f"lead_time must be in [1, {y_true_arr.shape[1]}], got {lead_time}."
                )
            residuals = y_true_arr[:, lead_time - 1] - y_pred_arr[:, lead_time - 1]
            plot_label = f"Residual (lead_time={lead_time})"
    else:
        raise ValueError(
            "y_true and y_pred must be 1-D or 2-D arrays. "
            f"Got ndim={y_true_arr.ndim}."
        )

    fig, axes = plt.subplots(1, 2, figsize=figsize)

    axes[0].plot(residuals, color="tab:blue", linewidth=1.5)
    axes[0].axhline(0.0, color="black", linestyle="--", linewidth=1)
    axes[0].set_title(plot_label)
    axes[0].set_xlabel("Sample")
    axes[0].set_ylabel("Residual")
    axes[0].grid(alpha=0.3)

    axes[1].hist(residuals, bins=bins, color="tab:orange", edgecolor="black", alpha=0.8)
    axes[1].axvline(residuals.mean(), color="black", linestyle="--", linewidth=1)
    axes[1].set_title("Residual distribution")
    axes[1].set_xlabel("Residual")
    axes[1].set_ylabel("Count")
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    return residuals


class ARXModel:
    """
    Autoregressive model with eXogenous inputs (ARX).
    
    Fits separate linear regression models for each lead time to predict
    multi-step ahead forecasts using past sequence values and future exogenous variables.
    """
    
    def __init__(self, verbose=False):
        self.models = {}  # Dictionary to store one model per lead time

    
    def train(self, X_seq_train, X_future_train, y_train, verbose=False):
        """
        Train ARX models for each lead time.
        
        Args:
            X_seq_train: (n_samples, n_lags, n_seq_features) - past sequence data
            X_future_train: (n_samples, n_lead_time, n_future_features) - future exogenous data
            y_train: (n_samples, n_lead_time) - multi-step targets
        """
        n_samples, n_lags, n_seq_features = X_seq_train.shape
        n_lead_time = y_train.shape[1]
        
        # Flatten past sequences: (n_samples, n_lags * n_seq_features)
        X_seq_flat = X_seq_train.reshape(n_samples, -1)
        
        # Flatten future exogenous: (n_samples, n_lead_time * n_future_features)
        X_future_flat = X_future_train.reshape(n_samples, -1)
        
        # Concatenate past and future features
        X_combined = np.hstack([X_seq_flat, X_future_flat])
        
        # Train separate model for each lead time
        for lead in range(n_lead_time):
            y_lead = y_train[:, lead]
            
            model = LinearRegression()
            model.fit(X_combined, y_lead)
            self.models[lead + 1] = model
            
            if verbose:
                r2_score = model.score(X_combined, y_lead)
                print(f"Lead time {lead + 1}: R² = {r2_score:.4f}")

    
    def predict(self, X_seq_test, X_future_test):
        """
        Predict multi-step ahead using ARX models.
        
        Args:
            X_seq_test: (n_samples, n_lags, n_seq_features) - past sequence data
            X_future_test: (n_samples, n_lead_time, n_future_features) - future exogenous data
        
        Returns:
            predictions: (n_samples, n_lead_time) - predicted values
        """
        n_samples, n_lags, n_seq_features = X_seq_test.shape
        n_lead_time = X_future_test.shape[1]
        
        # Flatten sequences
        X_seq_flat = X_seq_test.reshape(n_samples, -1)
        X_future_flat = X_future_test.reshape(n_samples, -1)
        
        # Concatenate
        X_combined = np.hstack([X_seq_flat, X_future_flat])
        
        # Predict for each lead time
        predictions = np.zeros((n_samples, n_lead_time))
        for lead in range(n_lead_time):
            predictions[:, lead] = self.models[lead + 1].predict(X_combined)
        
        return predictions


class ARXModelPerHourLead:
    """
    Separate linear ARX model for each (forecast_hour, lead_time) pair.

    Accepts datasets created by ``create_arx_datasets_by_hour_lead``. Because
    lag-dependent features are excluded for cross-day deliveries at dataset
    creation time, each model only sees the features relevant to its specific
    (hour, lead-time) context.
    """

    def __init__(self):
        self.models: dict[tuple[int, int], LinearRegression] = {}

    def train(self, datasets: dict) -> None:
        """Fit one LinearRegression per (forecast_hour, lead_time) pair.

        Args:
            datasets: output of ``create_arx_datasets_by_hour_lead``.
        """
        for key, ds in datasets.items():
            model = LinearRegression()
            model.fit(ds.X_train, ds.y_train)
            self.models[key] = model

    def predict(self, datasets: dict) -> dict[tuple[int, int], np.ndarray]:
        """Predict on each test set; returns values in the scaled target space.

        Returns:
            dict mapping (forecast_hour, lead_time) -> 1-D predicted array.
        """
        return {
            key: self.models[key].predict(ds.X_test)
            for key, ds in datasets.items()
            if key in self.models
        }


