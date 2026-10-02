import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import sys
from scipy.special import erfinv
from pathlib import Path

from src.paths import Paths
from src.load_config import Config
from src.forecasting import get_correct_time_indices
from src.forecast_data_handling import get_data

def plot_lead_time_correlation(config: Config):

    for error_type in config.error_types:
        for zone in config.zones_error_types[error_type]:
            # zone = "NO_2"
            data_path = Paths(config.run_id, error_type, zone).raw_forecasts
            y_test, y_pred, scaling_value, target_series, forecast_series = get_data(data_path)

            
            target_series = pd.Series(target_series.iloc[:, 0])    
            forecast_series = pd.Series(forecast_series.iloc[:, 0])
            
            flattened_pred = y_pred.reset_index().melt(id_vars='index')
            flattened_pred.columns = ['timestamp', 'lead_time', 'prediction']
            flattened_pred['delivery_time'] = flattened_pred['timestamp'] + pd.to_timedelta(flattened_pred['lead_time'].astype(int), unit='h')
            flattened_pred['actual'] = target_series.loc[flattened_pred['delivery_time']].values
            flattened_pred['da_forecast'] = forecast_series.loc[flattened_pred['delivery_time']].values
            flattened_pred['forecast_error'] = flattened_pred['prediction'] - flattened_pred['actual']
            # flattened_pred['square_forecast_error'] = flattened_pred['forecast_error'] ** 2
            # rmse_lead_time = flattened_pred.groupby('lead_time')['square_forecast_error'].mean() ** 0.5
            flattened_pred['lead_time'] = flattened_pred['lead_time'].astype(int)
            for delivery_time, group in flattened_pred.groupby('delivery_time'):
                if group.shape[0] < 8:
                    continue
                # group_sel = group.loc[group.lead_time.astype(int) < 8]
                # sort by lead time
                group_sorted = group.sort_values(by='lead_time')

                flattened_pred.loc[group_sorted.index, 'forecast_update'] = group_sorted['prediction'].diff(periods=-1)
            flattened_pred['forecast_update'].fillna(0, inplace=True)
    
            corr = pd.Series(index=flattened_pred['lead_time'].unique(), dtype=float)
            for lead_time, group in flattened_pred.groupby('lead_time'):
                corr[lead_time] = np.corrcoef(group['forecast_error'], group['forecast_update'])[0, 1]
            print(corr)
            quantile_drift = flattened_pred.groupby("lead_time")["forecast_update"].mean()
            flattened_pred['squared_error'] = flattened_pred['forecast_error'] ** 2
            mse = flattened_pred.groupby("lead_time")["squared_error"].mean()
            # mse_with_zero = mse.copy()
            
            # mse_with_zero.loc[0] = 0
            # mse_with_zero = mse_with_zero.sort_index()
            if "_" in config.run_id:
                quantile = int(config.run_id.split('_q')[1])
            quantile = 30
            z_score_normal = np.sqrt(2) * erfinv(2 * quantile / 100 - 1)


            mse_data_path = Paths("linear_nn", error_type, zone).raw_forecasts
            y_test, y_pred, scaling_value, target_series, forecast_series = get_data(mse_data_path)
            breakpoint()
            mse_calibrated = pd.Series(((y_test.values - y_pred.values) ** 2).mean(axis=0), index=y_pred.columns.astype(int))
            bias = pd.Series((y_test.values - y_pred.values).mean(axis=0), index=y_pred.columns.astype(int))
            std_calibrated = np.sqrt(mse_calibrated - bias ** 2)
            lead_times = std_calibrated.index.values
            expected_quantile_drift = z_score_normal * pd.Series(std_calibrated, index=lead_times).diff(periods=-1)
            rmse = np.sqrt(mse)

            from scipy.optimize import curve_fit

            def fit_func(x, a, b):
                return a * x / (x + b) 

            lead_times_with_zero = np.insert(lead_times, 0, 0)
            std_with_zero = np.insert(std_calibrated.values, 0, 0)
            popt, pcov = curve_fit(fit_func, lead_times_with_zero, std_with_zero)
            a_fit, b_fit = popt


            fitted_std = fit_func(lead_times, a_fit, b_fit)
            expected_analytical_drift =  z_score_normal * pd.Series(fitted_std, index=lead_times).diff(periods=-1)

            # expected_analytical_drift = expected_analytical_drift.shift(-1)
            savepath = Path(f"plots/{config.run_id}")
            savepath.mkdir(parents=True, exist_ok=True)

            plt.figure()
            plt.plot(lead_times[:-1], std_calibrated.values[:-1]/ scaling_value, label='Std')
            # plt.plot(lead_times, fitted_std/ scaling_value, label='Fitted Std')
            plt.legend()
            plt.savefig(savepath / f'rmse_fit_{zone}_{error_type}.png')
            plt.close()


            # expected_quantile_drift = expected_quantile_drift.shift(-1)
            expected_analytical_drift = pd.Series(expected_analytical_drift, index=lead_times)  # ?? 

            plt.figure()
            plt.plot(quantile_drift.index[:-1], quantile_drift.values[:-1]/ scaling_value, label='Observed quantile drift')
            plt.plot(expected_quantile_drift.index, expected_quantile_drift.values/ scaling_value, label='Expected quantile drift')
            # plt.plot(lead_times, expected_analytical_drift, label='Expected analytical drift')
            # plt.plot(lead_times, bias.diff(periods=-1), label='Incremental bias drift')
            plt.xlabel('Lead time [hour]')
            plt.ylabel('Quantile forecast drift [1/hour]')
            plt.legend()
            plt.savefig(savepath / f'quantile_drift_{zone}_{error_type}.png')
            plt.close()

            if False:
                # plt.figure()
                # plt.plot(rmse_lead_time.index, rmse_lead_time.values)
                # plt.show()
                # initialize correlation matrix
                corr_matrix = pd.DataFrame(index=lead_times, columns=lead_times, dtype=float)

                for lead_time in lead_times:
                    for prev_lead_time in lead_times:
                        if lead_time >= prev_lead_time:
                            corr_matrix.loc[lead_time, prev_lead_time] = np.nan
                            continue
                        
                        forecast_indices = pred_dict[lead_time].index
                        prev_forecast_indices = pred_dict[prev_lead_time].index
                        all_indices = forecast_indices.intersection(prev_forecast_indices)
                        if len(all_indices) == 0:
                            corr_matrix.loc[lead_time, prev_lead_time] = np.nan
                            continue
                        breakpoint()
                        corresponding_target = target_series.loc[all_indices]
                        forecast_error = scaling_value * pred_dict[lead_time].loc[all_indices] - corresponding_target.values
                        forecast_update = pred_dict[lead_time].loc[all_indices] - pred_dict[prev_lead_time].loc[all_indices]

                        corr = np.corrcoef(forecast_error, forecast_update)[0, 1]
                        corr_matrix.loc[lead_time, prev_lead_time] = corr

                # Plot heatmap
                plt.figure(figsize=(8, 6))
                sns.heatmap(corr_matrix.astype(float), annot=True, fmt=".2f", cmap="coolwarm", center=0)
                plt.title(f"Forecast Error vs Forecast Update Correlation\nZone: {zone}, Error type: {error_type}")
                plt.xlabel("Previous Lead Time")
                plt.ylabel("Current Lead Time")
                plt.show()

if __name__ == "__main__":
    config = Config('nordic.yaml')
    config.run_id = sys.argv[1] if len(sys.argv) > 1 else "default_run"
    plot_lead_time_correlation(config)
