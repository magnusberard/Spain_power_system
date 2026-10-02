import numpy as np
from sklearn.preprocessing import StandardScaler
from dataclasses import dataclass

from .load_config import Config

@dataclass
class DataSet:
    X_seq:  np.ndarray
    X_future: np.ndarray
    y: np.ndarray
    forecast_hour: np.ndarray


@dataclass
class StructuredDataForForecasting:
    train: DataSet
    test: DataSet
    y_scaler: StandardScaler
    seq_scaler: StandardScaler
    future_scaler: StandardScaler

def _apply_scaler(train_data, test_data, scaler: StandardScaler):
    train_2d = train_data.reshape(-1, 1)
    test_2d = test_data.reshape(-1, 1)
    train_scaled_2d = scaler.fit_transform(train_2d)
    test_scaled_2d = scaler.transform(test_2d)
    return train_scaled_2d.reshape(train_data.shape), test_scaled_2d.reshape(test_data.shape)


def create_supervised_dataset(
    target: np.ndarray,
    known_past_data: np.ndarray,
    known_future_data: np.ndarray,
    known_past_data_lag_dep: np.ndarray | None,
    forecast_hour_arr: np.ndarray | None,
    config: Config,
):
    """
    Create supervised dataset for multi-step forecasting with past sequences
    and future known data.

    Returns:

    """
    n_lags = config.n_lags
    n_lead_time = config.max_lead_time
    train_test_split = config.train_test_split
    
    X_seq, X_future, y = [], [], []
    sample_forecast_hours = []
    T = len(target)

    # Build the mask alongside X_seq and append it as an extra feature channel.

    for t in range(n_lags - 1, T - n_lead_time):
        forecast_hour_t = forecast_hour_arr[t]
        known_past_seq = known_past_data[t - n_lags + 1 : t + 1]

        if known_past_data_lag_dep is not None:
            lag_dep_seq = known_past_data_lag_dep[t - n_lags + 1 : t + 1].copy()
            combined_seq = np.hstack([known_past_seq, lag_dep_seq])

            # Track which lag_dep timesteps are unobservable
            mask = np.ones(n_lags, dtype=np.float64)
            if forecast_hour_t < n_lags - 1:
                mask[:n_lags - 1 - forecast_hour_t] = 0.0
            elif forecast_hour_t + n_lead_time >= 24 - n_lags + 1:
                mask[:] = 0.0
        else:
            combined_seq = known_past_seq
            mask = np.ones(n_lags, dtype=np.float64)  # nothing to mask
        # breakpoint()

        combined_seq_with_mask = np.hstack([combined_seq, mask[:, None]])

        X_seq.append(combined_seq_with_mask)
        X_future.append(known_future_data[t + 1 : t + n_lead_time + 1])
        sample_forecast_hours.append(forecast_hour_t)

        # --------------------------
        # Targets
        # --------------------------
        if single_lead_time:= False:
            y.append(target[t + n_lead_time])  # single-step target
        else:
            y.append(target[t + 1 : t + n_lead_time + 1])


    # Convert to arrays
    X_seq = np.array(X_seq, dtype=np.float64)
    
    X_future = np.array(X_future, dtype=np.float64)
    y = np.array(y, dtype=np.float64)
    sample_forecast_hours = np.array(sample_forecast_hours, dtype=np.int32)

    # --------------------------
    # Train/test split
    # --------------------------
    split = int(train_test_split * len(X_seq))
    X_seq_train, X_seq_test = X_seq[:split], X_seq[split:]
    X_future_train, X_future_test = X_future[:split], X_future[split:]
    y_train, y_test = y[:split], y[split:]
    forecast_hour_train, forecast_hour_test = sample_forecast_hours[:split], sample_forecast_hours[split:]

    # --------------------------
    # Scale past sequence features
    # --------------------------
    n_seq_features = X_seq.shape[2]
    seq_scaler = StandardScaler()

    X_seq_train_2d = X_seq_train.reshape(-1, n_seq_features)
    X_seq_train_features = seq_scaler.fit_transform(X_seq_train_2d[:, :-1])
    X_seq_train_2d = np.hstack([X_seq_train_features, X_seq_train_2d[:, -1:]])
    X_seq_train = X_seq_train_2d.reshape(
        X_seq_train.shape[0], n_lags, n_seq_features
    )

    X_seq_test_2d = X_seq_test.reshape(-1, n_seq_features)
    X_seq_test_features = seq_scaler.transform(X_seq_test_2d[:, :-1])
    X_seq_test_2d = np.hstack([X_seq_test_features, X_seq_test_2d[:, -1:]])
    X_seq_test = X_seq_test_2d.reshape(
        X_seq_test.shape[0], n_lags, n_seq_features
    )

    # --------------------------
    # Scale future-known features
    # --------------------------
    n_future_features = X_future.shape[2]
    future_scaler = StandardScaler()

    X_future_train_2d = X_future_train.reshape(-1, n_future_features)
    X_future_train_2d = future_scaler.fit_transform(X_future_train_2d)
    X_future_train = X_future_train_2d.reshape(
        X_future_train.shape[0], n_lead_time, n_future_features
    )

    X_future_test_2d = X_future_test.reshape(-1, n_future_features)
    X_future_test_2d = future_scaler.transform(X_future_test_2d)
    X_future_test = X_future_test_2d.reshape(
        X_future_test.shape[0], n_lead_time, n_future_features
    )

    # --------------------------
    # Scale targets
    # --------------------------
    y_scaler = StandardScaler()
    y_train, y_test = _apply_scaler(y_train, y_test, y_scaler)



    return StructuredDataForForecasting(
        train=DataSet(
            X_seq=X_seq_train,
            X_future=X_future_train,
            y=y_train,
            forecast_hour=forecast_hour_train,
        ),
        test=DataSet(
            X_seq=X_seq_test,
            X_future=X_future_test,
            y=y_test,
            forecast_hour=forecast_hour_test,
        ),
        y_scaler=y_scaler,
        seq_scaler=seq_scaler,
        future_scaler=future_scaler,
    )




@dataclass
class ARXSampleSet:
    """Flat feature matrix and targets for one (forecast_hour, lead_time) pair."""
    X_train: np.ndarray           # (n_train, n_features)
    y_train: np.ndarray           # (n_train,)
    X_test: np.ndarray            # (n_test, n_features)
    y_test: np.ndarray            # (n_test,)
    y_scaler: StandardScaler
    x_scaler: StandardScaler
    train_time_indices: np.ndarray  # position t in original time series (forecast time)
    test_time_indices: np.ndarray


def create_arx_datasets_by_hour_lead(
    target: np.ndarray,
    known_past_data: np.ndarray,
    known_future_data: np.ndarray,
    known_past_data_lag_dep: np.ndarray | None,
    forecast_hour_arr: np.ndarray,
    config: Config,
) -> dict[tuple[int, int], ARXSampleSet]:
    """
    Build one flat ARX dataset per (forecast_hour, lead_time) pair.

    Lag-dependent features are included only when the delivery falls on the
    same calendar day as the forecast (forecast_hour + lead_time < 24), because
    the lag-dependent data (e.g. DA forecast errors) belongs to the current
    day's DA round and is irrelevant for next-day deliveries.

    Args:
        target: 1-D array of length T.
        known_past_data: (T, n_past_features) always-available past features.
        known_future_data: (T, n_future_features); index t+l gives delivery-time features.
        known_past_data_lag_dep: (T, n_lag_dep_features) or None. Conditionally included.
        forecast_hour_arr: 1-D int array, hour-of-day (0–23) for each time step.
        config: supplies n_lags, max_lead_time, train_test_split.

    Returns:
        dict mapping (forecast_hour, lead_time) -> ARXSampleSet.
    """
    n_lags = config.n_lags
    n_lead_time = config.max_lead_time
    train_test_split = config.train_test_split
    T = len(target)

    # Accumulate raw samples per (h, l) pair in time order.
    raw: dict[tuple[int, int], dict] = {}

    for t in range(n_lags - 1, T):
        h = int(forecast_hour_arr[t])
        past_seq = known_past_data[t - n_lags + 1 : t + 1]        # (n_lags, n_past_f)
        lag_hours = forecast_hour_arr[t - n_lags + 1 : t + 1].astype(int)
        lag_dep_seq = (
            known_past_data_lag_dep[t - n_lags + 1 : t + 1]
            if known_past_data_lag_dep is not None
            else None
        )

        for lead in range(1, n_lead_time + 1):
            if t + lead >= T:
                break

            # Lag-dependent features are only valid for same-day deliveries.
            same_day = (h + lead) < 24
            if lag_dep_seq is not None and same_day:
                # Keep lag-dependent values only from the current day up to hour h.
                # Example: at h=2 this keeps hours 0,1,2 and drops 23 from previous day.
                current_day_mask = (lag_hours <= h).astype(np.float64)[:, None]
                lag_dep_seq_filtered = lag_dep_seq * current_day_mask
                seq_flat = np.hstack([past_seq, lag_dep_seq_filtered]).ravel()
            else:
                seq_flat = past_seq.ravel()

            X_row = np.concatenate([seq_flat, known_future_data[t + lead]])

            key = (h, lead)
            if key not in raw:
                raw[key] = {"X": [], "y": [], "t": []}
            raw[key]["X"].append(X_row)
            raw[key]["y"].append(target[t + lead])
            raw[key]["t"].append(t)

    # Convert lists to arrays, split chronologically, then scale.
    datasets: dict[tuple[int, int], ARXSampleSet] = {}

    for key, data in raw.items():
        X = np.array(data["X"], dtype=np.float64)
        y = np.array(data["y"], dtype=np.float64)
        t_indices = np.array(data["t"], dtype=np.int64)

        split = int(train_test_split * len(X))
        if split == 0 or split == len(X):
            continue

        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]
        train_idx, test_idx = t_indices[:split], t_indices[split:]

        x_scaler = StandardScaler()
        X_train = x_scaler.fit_transform(X_train)
        X_test = x_scaler.transform(X_test)

        y_scaler = StandardScaler()
        y_train = y_scaler.fit_transform(y_train.reshape(-1, 1)).ravel()
        y_test = y_scaler.transform(y_test.reshape(-1, 1)).ravel()

        datasets[key] = ARXSampleSet(
            X_train=X_train,
            y_train=y_train,
            X_test=X_test,
            y_test=y_test,
            y_scaler=y_scaler,
            x_scaler=x_scaler,
            train_time_indices=train_idx,
            test_time_indices=test_idx,
        )

    return datasets
