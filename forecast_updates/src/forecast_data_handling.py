import pickle
import numpy as np
import pandas as pd
from pathlib import Path


def save_data(forecast_output_path: Path, y_test_df, y_pred_df, scaling_value, target_series, forecast_series):
    forecast_output_path.mkdir(parents=True, exist_ok=True)
    y_test_df.to_csv(forecast_output_path / "y_test.csv")
    y_pred_df.to_csv(forecast_output_path / "y_pred.csv")
    
    # save scaling value to .csv
    with open(forecast_output_path / "scaling_value_mw.csv", "w") as f:
        f.write(str(scaling_value))
    # save target and forecast series as CSV files
    target_series.to_csv(forecast_output_path / "target_series.csv")
    forecast_series.to_csv(forecast_output_path / "forecast_series.csv")


        

def get_data(forecast_output_path: Path):
    y_test_df = pd.read_csv(forecast_output_path / "y_test.csv", index_col=0, parse_dates=True)
    y_pred_df = pd.read_csv(forecast_output_path / "y_pred.csv", index_col=0, parse_dates=True)
    with open(forecast_output_path / "scaling_value_mw.csv", "r") as f:
        scaling_value = float(f.read().strip())
    target_series = pd.read_csv(forecast_output_path / "target_series.csv", index_col=0, parse_dates=True)
    forecast_series = pd.read_csv(forecast_output_path / "forecast_series.csv", index_col=0, parse_dates=True)

    return y_test_df, y_pred_df, scaling_value, target_series, forecast_series


