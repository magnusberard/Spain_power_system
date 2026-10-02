import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from src.load_config import Config
from src.fitting import calc_fitting_params_loop
from src.utils import select_day, validate_day_indexing
from src.forecasting import get_correct_time_indices, load_input_data
from src.forecast_data_handling import get_data
from src.post_process import restructure_forecast_df, normalize_to_day_ahead, load_omie_data, convert_to_omie
from src.utils import make_dir
from src.plotting.rmse import plot_rmse


    
def analyze_corr(config_yaml_name: str, plotting_flag: bool = False):
    config = Config(config_yaml_name)
    years = config.years
    for error_type in config.error_types:
        print(error_type)
        target_series_dict = {}
        forecast_series_dict = {}
        for zone in config.zones_error_types[error_type]:
            # y_test_dict, y_pred_dict, scaling_value, target_series, forecast_series = get_data(forecast_pickle_dir=f"data/pickled_forecasts/{config.run_id}", zone=zone, error_type=error_type)
            input_data = load_input_data(years, zone, error_type)
            target_series = input_data.target_series
            forecast_series = input_data.forecast_series
            target_series = pd.Series(target_series)    
            forecast_series = pd.Series(forecast_series)
            

            corr = np.corrcoef(forecast_series, np.abs(forecast_series - target_series))[1,0]
            # print(f"Corr coeff for zone {zone}: {corr}")

            # print(np.mean(forecast_series - target_series)/np.mean(target_series))
            # Trend line (linear fit)
            x = np.asarray(forecast_series)
            y = np.abs(x - target_series)

            coef = np.polyfit(x, y, 1)          # linear fit: y = a*x + b
            trend = np.poly1d(coef)

            x_fit = np.linspace(x.min(), x.max(), 200)
            y_fit = trend(x_fit)

            target_series_dict[zone] = target_series
            forecast_series_dict[zone] = forecast_series
            
            if plotting_flag:
                plt.figure()
                plt.scatter(forecast_series, np.abs(forecast_series - target_series), s=0.001)
                plt.plot(x_fit, y_fit, linewidth=2)
                plt.show()
        # calculate correlation matrix of target_series between zones
        all_targets = pd.DataFrame(target_series_dict)
        correlation_matrix = all_targets.corr()
        print("Correlation matrix between zones:")
        print(correlation_matrix)
        # calculate correlation matrix of target_series - forecast_series
        all_errors = all_targets - pd.DataFrame(forecast_series_dict)
        correlation_matrix = all_errors.corr()
        print("Correlation matrix of forecast errors between zones:")
        print(correlation_matrix)

if __name__ == "__main__":
    analyze_corr(config_yaml_name='nordic.yaml')