from dataclasses import dataclass
import pandas as pd
import numpy as np

from typing import Callable
from sklearn.preprocessing import StandardScaler

from .load_saved_data import (
    load_load_data,
    load_generation_data,
    InputData
)
from .utils import make_dir
from .load_config import Config
from .forecast_data_handling import save_data
from .algorithms.get_algorithm import ForecastingModel, get_forecasting_model
# [Spain_power_system] unused here, and it pulls in TensorFlow at import time
# from .algorithms.linear_nn import LinearNNModel
from .algorithms.linear import LinearMultiStepModel
from .create_multivariate_input import create_supervised_dataset, StructuredDataForForecasting


def get_correct_time_indices(y_pred_dict, target_index, max_lead_time):
        pred_dict = {}
        for n_lead_time in range(1, max_lead_time + 1):
                start_index = target_index.size - y_pred_dict[n_lead_time].size
                y_pred_ser = pd.Series(y_pred_dict[n_lead_time].values, index=target_index[start_index:])
                pred_dict[n_lead_time] = y_pred_ser
        
        return pred_dict


def load_input_data(years, zone, error_type, data_folder="data/input_entsoe") -> InputData:
    if error_type == "load":
        input_data = load_load_data(years, zone, folder=data_folder)
    else:
        input_data = load_generation_data(years, zone, folder=data_folder, carrier=error_type)
    if input_data.target_series.isna().sum() > 10:
        raise ValueError(f"Target series for {zone} in {error_type} has too many NaN values. Please check the data.")

    return input_data


def define_data_inputs(target_series, da_forecast_series, use_observed_values):
    
    difference = target_series - da_forecast_series

    target_series_hour_sin = np.sin(target_series.index.hour * (2 * np.pi / 24))
    target_series_series_dayofyear_sin = np.sin(target_series.index.dayofyear * (2 * np.pi / 365))
    target_series_hour_cos = np.cos(target_series.index.hour * (2 * np.pi / 24))
    target_series_series_dayofyear_cos = np.cos(target_series.index.dayofyear * (2 * np.pi / 365))
    # day of week indicator 
    target_series_dayofweek = target_series.index.dayofweek
    is_weekend = target_series_dayofweek.isin([5, 6]).astype(int)
    
    forecast_hour_arr = target_series.index.hour.values

    known_future_data = np.column_stack((
        da_forecast_series.values,
        target_series_hour_sin.values,
        target_series_hour_cos.values,
        target_series_series_dayofyear_sin.values,
        target_series_series_dayofyear_cos.values,
        is_weekend,
        )).astype(np.float32)
    
    if use_observed_values:
        known_past_data = np.column_stack((
            target_series.values, 
            # target_series_hour_sin.values,
            # target_series_hour_cos.values,
            # target_series_series_dayofyear_sin.values,
            # target_series_series_dayofyear_cos.values,
            # is_weekend,
            )).astype(np.float32)
        
        known_past_data_lag_dep = np.column_stack((
            difference.values, 
            da_forecast_series.values,
            )).astype(np.float32)

    else:
        known_past_data = np.column_stack((
            target_series_hour_sin.values,
            target_series_hour_cos.values,
            target_series_series_dayofyear_sin.values,
            target_series_series_dayofyear_cos.values,
            is_weekend,
            )).astype(np.float32)
        known_past_data_lag_dep = None

    return UnstructuredDataForForecasting(
        known_past_data=known_past_data,
        known_past_data_lag_dep=known_past_data_lag_dep,
        forecast_hour_arr=forecast_hour_arr,
        known_future_data=known_future_data
    )



def _reshape_forecasting_output(y_pred_scaled, y_test, y_scaler, target_series, config: Config):
    max_lead_time = config.max_lead_time
    n_lags = config.n_lags
    train_test_split = config.train_test_split
    lead_time_range = config.lead_time_range

    # --- inverse transform BOTH ---
    y_pred = y_scaler.inverse_transform(
        y_pred_scaled.reshape(-1, 1)
    ).reshape(y_pred_scaled.shape)

    y_test_inv = y_scaler.inverse_transform(
        y_test.reshape(-1, 1)
    ).reshape(y_test.shape)
    N = len(target_series)
    n_samples = N - n_lags - max_lead_time + 1
    split = int(train_test_split * n_samples)

    index = target_series.index[
        (n_lags - 1) + split : (n_lags - 1) + split + y_test.shape[0]
    ]

    y_test_df = pd.DataFrame(y_test_inv, columns=lead_time_range, index=index)
    y_pred_df = pd.DataFrame(y_pred, columns=lead_time_range, index=index)
    return y_test_df, y_pred_df


@dataclass 
class UnstructuredDataForForecasting:
    known_past_data: np.ndarray
    known_past_data_lag_dep: np.ndarray | None
    forecast_hour_arr: np.ndarray | None
    known_future_data: np.ndarray
     


def get_forecasts(
        target_series: pd.Series, 
        da_forecast_series: pd.Series,
        config: Config,
        use_observed_values: bool = True,
        ) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """
    Calculate RMSE w.r.t. lead time for each zone and fit the asymptotic function to the RMSE values. 
    Returns the test values and predictions for each lead time.
    Optionally saves the results as pickle files.

    Args:
        error_type (str): Type of error to forecast, e.g., 'load', 'Wind Onshore', 'Solar'.
        zone (str): Zone for which to calculate the forecasts. Must conform with ENTSO-E convention. 
        years (list[int]): List of years for which to calculate the forecasts.
        train_and_test_function (Callable): Function to train and test the model (in src.algorithms)
        n_lags (int, optional): Number of lags to use in the model. Defaults to 3.
        lead_time_range (range | list[int], optional): Range of lead times to consider. Defaults to range(1, 13).
        data_folder (str, optional): Folder where input data is stored. Defaults to "data/input_entsoe".
        train_test_split (float, optional): Proportion of data to use for training. Defaults to 0.8.
        pickle_output_flag (bool, optional): Whether to save the results as pickle files. Defaults to True.
        forecast_pickle_dir (str, optional): Directory where pickle files will be saved. Defaults to "data/pickled_forecasts".
        model_name (str, optional): Name of the model to use ('LSTM' or 'ARX'). Defaults to 'LSTM'.

    """

    forecasting_model: ForecastingModel = get_forecasting_model(config.forecasting_model)

    
    unstructured_data = define_data_inputs(target_series, da_forecast_series, use_observed_values)

    structured_data = create_supervised_dataset(
        target=target_series.values,
        known_past_data=unstructured_data.known_past_data,
        known_future_data=unstructured_data.known_future_data,
        known_past_data_lag_dep=unstructured_data.known_past_data_lag_dep,
        forecast_hour_arr=unstructured_data.forecast_hour_arr,
        config=config,
    )
    if use_observed_values:
        forecasting_model.train(
            structured_data.train.X_seq,
            structured_data.train.X_future,
            structured_data.train.y,
            verbose=True,
            **config.training_params
            )
        y_pred = forecasting_model.predict(structured_data.test.X_seq, structured_data.test.X_future)
    else:
        # If not using observed values, train on all available data (no train-test split)
        forecasting_model.train(
            None,
            structured_data.train.X_future,
            structured_data.train.y,
            verbose=True,
            **config.training_params
            )
        y_pred = forecasting_model.predict(
            None,
            structured_data.test.X_future
        )
    
    


    y_test_df, y_pred_df = _reshape_forecasting_output(
        y_pred_scaled=y_pred,
        y_test=structured_data.test.y,
        y_scaler=structured_data.y_scaler,
        target_series=target_series,
        config=config,
        )
    
    
    return y_test_df, y_pred_df


def get_forecasts_arx_per_hour_lead(
        target_series: pd.Series,
        da_forecast_series: pd.Series,
        config: Config,
        use_observed_values: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    ARX forecasting with one model per (forecast_hour, lead_time) pair.

    Lag-dependent features (e.g. DA forecast errors for the current day) are
    only included when the delivery falls on the same calendar day as the
    forecast hour (forecast_hour + lead_time < 24).  For cross-day deliveries
    the model uses base past features and future exogenous only.

    Returns the same (y_test_df, y_pred_df) tuple as ``get_forecasts``:
    both DataFrames are indexed by forecast time, columns are lead times.
    """
    from .create_multivariate_input import create_arx_datasets_by_hour_lead
    from .algorithms.arx import ARXModelPerHourLead

    unstructured_data = define_data_inputs(target_series, da_forecast_series, use_observed_values)

    datasets = create_arx_datasets_by_hour_lead(
        target=target_series.values,
        known_past_data=unstructured_data.known_past_data,
        known_future_data=unstructured_data.known_future_data,
        known_past_data_lag_dep=unstructured_data.known_past_data_lag_dep,
        forecast_hour_arr=unstructured_data.forecast_hour_arr,
        config=config,
    )

    model = ARXModelPerHourLead()
    model.train(datasets)
    predictions_scaled = model.predict(datasets)

    lead_times = list(config.lead_time_range)

    # Collect per-(t, l) predictions and targets in original scale.
    pred_by_t: dict[int, dict[int, float]] = {}
    test_by_t: dict[int, dict[int, float]] = {}

    for (h, lead), y_pred_scaled in predictions_scaled.items():
        ds = datasets[(h, lead)]
        y_pred = ds.y_scaler.inverse_transform(y_pred_scaled.reshape(-1, 1)).ravel()
        y_test = ds.y_scaler.inverse_transform(ds.y_test.reshape(-1, 1)).ravel()

        for i, t in enumerate(ds.test_time_indices):
            if t not in pred_by_t:
                pred_by_t[t] = {}
                test_by_t[t] = {}
            pred_by_t[t][lead] = float(y_pred[i])
            test_by_t[t][lead] = float(y_test[i])

    sorted_t = sorted(pred_by_t.keys())
    index = target_series.index[sorted_t]

    y_pred_df = pd.DataFrame(
        [{lt: pred_by_t[t].get(lt, np.nan) for lt in lead_times} for t in sorted_t],
        index=index,
        columns=lead_times,
    )
    y_test_df = pd.DataFrame(
        [{lt: test_by_t[t].get(lt, np.nan) for lt in lead_times} for t in sorted_t],
        index=index,
        columns=lead_times,
    )

    return y_test_df, y_pred_df


def get_forecasts_single_step_no_observed(
        target_series: pd.Series, 
        da_forecast_series: pd.Series,
        config: Config,
        ) -> pd.DataFrame:
    """
    Generate single-step forecasts without using recently observed values.
    
    This function makes one forecast at each time step in the target series using only
    the DA forecast, calendar features, and past differences/forecasts (no recent observations).
    Always uses the LINEAR_NN model.
    
    Args:
        target_series (pd.Series): Target variable time series.
        da_forecast_series (pd.Series): Day-ahead forecast series.
        config (Config): Configuration object with model parameters.
    
    Returns:
        pd.DataFrame: Single-step forecasts with datetime index and one column 'forecast'.
    """
    
    # Use LINEAR model
    forecasting_model: ForecastingModel = LinearMultiStepModel()
    
    # Define data inputs without observed values
    unstructured_data = define_data_inputs(target_series, da_forecast_series, use_observed_values=False)
    
    # Create supervised dataset for training
    structured_data = create_supervised_dataset(
        target=target_series.values,
        known_past_data=unstructured_data.known_past_data,
        known_future_data=unstructured_data.known_future_data,
        known_past_data_lag_dep=unstructured_data.known_past_data_lag_dep,
        forecast_hour_arr=unstructured_data.forecast_hour_arr,
        config=config,
    )
    
    # Train the model on all available training data
    forecasting_model.train(
        structured_data.train.X_seq,
        structured_data.train.X_future,
        structured_data.train.y,
        verbose=True,
        **config.training_params
    )
    
    # Make predictions on test set
    y_pred_scaled = forecasting_model.predict(
        structured_data.test.X_seq,
        structured_data.test.X_future
    )
    
    # Inverse transform predictions to original scale
    y_pred = structured_data.y_scaler.inverse_transform(
        y_pred_scaled.reshape(-1, 1)
    ).reshape(y_pred_scaled.shape)
    
    # Extract only the first lead time (1-step ahead forecast)
    y_pred_1step = y_pred[:, 0]
    
    # Create index for predictions
    n_lags = config.n_lags
    max_lead_time = config.max_lead_time
    train_test_split = config.train_test_split
    
    N = len(target_series)
    n_samples = N - n_lags - max_lead_time + 1
    split = int(train_test_split * n_samples)
    
    index = target_series.index[
        (n_lags - 1) + split + 1 : (n_lags - 1) + split + 1 + y_pred_1step.shape[0]
    ]
    
    # Create output DataFrame
    forecast_df = pd.DataFrame(
        y_pred_1step,
        index=index,
        columns=['forecast']
    )
    
    return forecast_df





