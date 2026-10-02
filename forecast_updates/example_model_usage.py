"""
Example usage of different forecasting models (LSTM vs ARX).

This script demonstrates how to use both the LSTM and ARX models
for forecasting with exogenous inputs.
"""

from src.algorithms.lstm import train_and_test_lstm
from src.algorithms.arx import train_and_test_arx
from src.forecasting import get_model_function, get_forecasts
import numpy as np

# Example: Get model function by name
# =====================================

# Option 1: Get LSTM model
lstm_fn = get_model_function('LSTM')
print(f"Selected model function: {lstm_fn.__name__}")

# Option 2: Get ARX model
arx_fn = get_model_function('ARX')
print(f"Selected model function: {arx_fn.__name__}")

# Example: Using models in get_forecasts
# =======================================

"""
In your forecasting pipeline, you can now pass the model_name parameter:

y_test_df, y_pred_df = get_forecasts(
    target_series=target_series,
    da_forecast_series=da_forecast_series,
    train_and_test_function=train_and_test_function,
    n_lags=4,
    lead_time_range=range(1, 13),
    train_test_split=0.8,
    model_name='ARX'  # or 'LSTM'
)
"""

# Example: Directly using ARX model
# ==================================

# Create dummy data
n_samples = 100
n_lags = 4
n_lead_time = 12
n_seq_features = 8
n_future_features = 7

X_seq_train = np.random.randn(n_samples, n_lags, n_seq_features).astype(np.float32)
X_future_train = np.random.randn(n_samples, n_lead_time, n_future_features).astype(np.float32)
y_train = np.random.randn(n_samples, n_lead_time).astype(np.float32)

X_seq_test = np.random.randn(20, n_lags, n_seq_features).astype(np.float32)
X_future_test = np.random.randn(20, n_lead_time, n_future_features).astype(np.float32)

# Train ARX model
print("\nTraining ARX model...")
arx_model = train_and_test_arx(
    X_seq_train,
    X_future_train,
    y_train,
    verbose=True
)

# Make predictions
print("\nMaking predictions...")
y_pred = arx_model.predict(X_seq_test, X_future_test)
print(f"Predictions shape: {y_pred.shape}")
print(f"Sample predictions:\n{y_pred[:3]}")
