import sys

from src.forecast_data_handling import save_data
from src.paths import Paths
from src.forecasting import (
    get_forecasts,
    get_forecasts_arx_per_hour_lead,
    load_input_data,
    get_forecasts_single_step_no_observed,
)
from src.load_config import Config
import pandas as pd 

def make_forecast_loop(
        config: Config, 
        use_observed_values: bool = True,
        ):
    """Generate intraday forecasts for all zones and error types specified in the config file.

    """
    years = config.years

    for error_type in config.error_types:
        print(error_type)
        zones = config.zones_error_types[error_type]
        for zone in zones:
            input_data = load_input_data(years, zone, error_type)
            # if error_type == 'load':
            #     import matplotlib.pyplot as plt
            #     plt.figure()
            #     plt.plot(input_data.target_series.iloc[:1000], label='Actual Load')
            #     plt.plot(input_data.forecast_series.iloc[:1000], label='Forecasted Load')
            #     plt.legend()
            #     plt.title(f"Load and Forecast for {zone} (first 1000 hours)")
            #     plt.show()
            # get_forecasts_single_step_no_observed(
            #     target_series=input_data.target_series,
            #     da_forecast_series=input_data.forecast_series,
            #     config=config
            # )
            import numpy as np
            y = input_data.target_series.values
            x = np.arange(len(y))
            x = np.arange(len(y))
            coeffs = np.polyfit(x, y, 1)
            trend = np.polyval(coeffs, x)
            trend = pd.Series(trend, index=input_data.target_series.index)
            
            input_data.target_series -= trend
            input_data.forecast_series -= trend
    
            forecast_bias =  (input_data.forecast_series - input_data.target_series).mean()
            input_data.forecast_series -= forecast_bias
            
            coeff = coeffs[0]
            print(f"Trend coefficient for {zone} in {error_type}: {8670 * coeff:.4f} MW/year")
            

            forecast_fn = get_forecasts_arx_per_hour_lead if config.forecasting_model.upper() == 'ARX' else get_forecasts
            y_test, y_pred = forecast_fn(
                target_series=input_data.target_series,
                da_forecast_series=input_data.forecast_series,
                config=config,
                use_observed_values=use_observed_values,
                )
            
            # y_test_no_obs, y_pred_no_obs = forecast_fn(
            #     target_series=input_data.target_series,
            #     da_forecast_series=input_data.forecast_series,
            #     config=config,
            #     use_observed_values=False,
            #     )

            
            y_test = y_test.astype('float64')
            y_pred = y_pred.astype('float64')
            
            index_intersection = y_test.index.intersection(trend.index)

            y_test.loc[index_intersection] = y_test.loc[index_intersection].add(trend.loc[index_intersection], axis=0) 
            y_pred.loc[index_intersection] = y_pred.loc[index_intersection].add(trend.loc[index_intersection], axis=0)
            input_data.target_series += trend
            input_data.forecast_series += trend
            input_data.forecast_series += forecast_bias


            save_data(forecast_output_path=Paths(config.run_id, error_type, zone).raw_forecasts, 
                      y_test_df=y_test, 
                      y_pred_df=y_pred, 
                      scaling_value=input_data.scaling_value,
                      target_series=input_data.target_series, 
                      forecast_series=input_data.forecast_series
                      )


if __name__ == "__main__":
    # specify config file as input parameter, such that we run this script as python make_forecasts.py [RUN_ID] 
    config_file = 'nordic.yaml'
    config = Config(config_file)
    config.run_id = sys.argv[1] if len(sys.argv) > 1 else "default_run"
    # config.use_observed_values = False
    # config.training_params['loss'] = 'quantile-50'
    config.forecasting_model = 'LINEAR'
    # config.generation_error_types = []
    # config.error_types = ['load']
    make_forecast_loop(config, use_observed_values=True)


    # config.training_params['loss'] = 'quantile-30'
    # config.run_id = "nordic_nn30"
    # make_forecast_loop(config, True)

    # config.training_params['loss'] = 'quantile-70'
    # config.run_id = "nordic_nn70"
    # make_forecast_loop(config, True)


    # config = Config('nordic.yaml')
    # config.run_id = "nordic_lstm"
    # config.forecasting_model = "LSTM"
    # make_forecast_loop(config)

    # config = Config('nordic.yaml')
    # config.run_id = "nordic_linear"
    # config.forecasting_model = "LINEAR"
    # make_forecast_loop(config)

    # from main import main
    # dates_2024 = pd.date_range(start="2024-01-01", end="2024-12-31", freq="D", tz='UTC')
    # config_yaml_name = 'nordic.yaml'
    # config = Config(config_yaml_name)
    # main(config=config, dates=dates_2024,
    #         plotting_flag=True)


