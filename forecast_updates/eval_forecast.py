

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from src.paths import Paths
from src.load_config import Config
from src.forecasting import get_correct_time_indices
from src.forecast_data_handling import get_data

def evaluate_forecast(config_yaml_name: str):
    config = Config(config_yaml_name)

    for error_type in config.error_types:
        for zone in config.zones_error_types[error_type]:
            data_path = Paths(config.run_id, error_type, zone).raw_forecasts
            y_test, y_pred, scaling_value, target_series, forecast_series = get_data(data_path)
            rmse = (((y_test - y_pred) ** 2).mean() ** 0.5).mean()
            bias = (y_pred - y_test).mean().mean()
            print(f"Zone: {zone}, Error Type: {error_type}, RMSE: {rmse}, Bias: {bias}")

if __name__ == "__main__":
    evaluate_forecast('nordic.yaml')