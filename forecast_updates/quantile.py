
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import sys 

from src.plotting.plotting_config import PLOTTING_PARAMS
from src.paths import Paths
from src.load_config import Config
from src.fitting import calc_fitting_params_loop
from src.utils import select_day, validate_day_indexing
from src.forecasting import get_correct_time_indices
from src.forecast_data_handling import get_data
from src.post_process import restructure_forecast_df, normalize_to_day_ahead, load_omie_data, convert_to_omie
from src.utils import make_dir
from src.plotting.rmse import plot_rmse



def compile_gate_forecasts(
        y_pred: pd.DataFrame,
        target_series: pd.Series,
        forecast_series: pd.Series,
        date: pd.Timestamp,
    ) -> pd.DataFrame:



    gate_time_dict = {
        "DA": date - pd.Timedelta(hours=12),  # DA
        # "ID1": date - pd.Timedelta(hours=9),   # IDA 1
        "ID2": date - pd.Timedelta(hours=2),   # IDA 2
        "ID3": date + pd.Timedelta(hours=10),  # IDA 3
        "CID": pd.DatetimeIndex([date + pd.Timedelta(hours=hr) for hr in range(-1, 23)]),  # CID
        # "BE": pd.DatetimeIndex([date + pd.Timedelta(hours=hr) for hr in range(24)])  # BE
    }

    all_delivery_hours = pd.date_range(start=date, periods=24, freq='h', tz='UTC')
    second_half_delivery_hours = all_delivery_hours[12:]

    delivery_hours = {
        "DA": all_delivery_hours,
        # "ID1": all_delivery_hours,
        "ID2": all_delivery_hours,
        "ID3": second_half_delivery_hours,
        "CID": all_delivery_hours,
        "BE": all_delivery_hours
    }
    
    gate_forecasts = pd.DataFrame(index=all_delivery_hours, columns=gate_time_dict.keys(), dtype=float)

    for gate_name, gate_time in gate_time_dict.items():
        gate_delivery_hours = delivery_hours[gate_name]
        # breakpoint()
        forecast_data = y_pred.loc[gate_time].copy()

        if gate_name == "CID":
            delivery_time = gate_time + pd.to_timedelta(1, unit="h")
            forecast_data_timeindexed = forecast_data[1].copy()
            forecast_data_timeindexed.index = delivery_time
        else:
            delivery_time = pd.DatetimeIndex(gate_time + pd.to_timedelta(forecast_data.index.astype(int), unit="h"))
            forecast_data_timeindexed = forecast_data.copy()
            forecast_data_timeindexed.index = delivery_time

        delivery_hours_within_forecast_range = delivery_time[(delivery_time >= gate_delivery_hours.min()) & (delivery_time <= gate_delivery_hours.max())]
        gate_forecasts.loc[delivery_hours_within_forecast_range, gate_name] = forecast_data_timeindexed.loc[delivery_hours_within_forecast_range].values

    gate_forecasts["BE"] = target_series.loc[gate_forecasts.index]
    gate_forecasts["DA"] = forecast_series.loc[gate_forecasts.index]
    # fill NaN values with value on the left
    # breakpoint()
    gate_forecasts = gate_forecasts.ffill(axis=1)
    return gate_forecasts


def collect_forecasts(config, error_type, lead_times=None) -> dict:
    y_pred_dict = {}
    y_test_dict = {}
    forecast_series_dict = {}
    target_series_dict = {}

    for zone in config.zones_error_types[error_type]:
        raw_forecast_path = Paths(config.run_id, error_type, zone).raw_forecasts
        y_test, y_pred, _, target_series, forecast_series = get_data(forecast_output_path=raw_forecast_path)

        if lead_times is not None:
            y_pred = y_pred[lead_times]
            y_test = y_test[lead_times]
        y_pred_dict[zone] = y_pred
        y_test_dict[zone] = y_test
        forecast_series_dict[zone] = forecast_series
        target_series_dict[zone] = target_series

    return y_pred_dict, y_test_dict, forecast_series_dict, target_series_dict

def plot_error_histogram(
        ax: plt.Axes, 
        error_df: pd.DataFrame, 
        plot_path: Path,
        n_bins=60,
        xlim=(-1000, 1000),
        ylabel="Frequency [-]",
        xlabel="Forecast error [MW]",
        lead_times=None,
        ) -> None:
    error_df.index.name = "Lead Time"
    if lead_times is not None:
        error_df = error_df[lead_times]
    error_df_melted = error_df.melt(var_name="Lead Time", value_name="forecast_error")
    sns.histplot(
        ax=ax,
        data=error_df_melted,
        x="forecast_error",
        hue="Lead Time",
        bins=np.linspace(xlim[0], xlim[1], n_bins),
        element="step",
        stat="count",
        common_norm=False,
        palette={'1': 'tab:blue', '2': 'tab:orange', '4': 'tab:green', '8': 'tab:red'},
    )
    ax.set_xlim(xlim)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return 

def plot_stats(y_test, y_pred, target_series, forecast_series, config, zone, error_type):
        # breakpoint()
        plt.figure()
        rmse = ((y_test - y_pred) ** 2).mean() ** 0.5
        rmse_da = (target_series - forecast_series).pow(2).mean() ** 0.5
        plt.plot(rmse, label='Intraday RMSE')
        plt.axhline(rmse_da.values[0], color='k', linestyle='--', label='ENTSO-E DA RMSE')
        print(config.run_id)
        print(f"plots/{config.run_id}/{zone}_{error_type}_rmse.png")
        plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_rmse.png", bbox_inches='tight')
        plt.close()

        # plot bias
        plt.figure()
        bias = (y_pred - y_test).mean()
        bias_da = (forecast_series - target_series).mean().values[0]
        plt.plot(bias, label='Intraday Bias')
        plt.axhline(bias_da, color='k', linestyle='--', label='Day-ahead Bias')
        plt.legend()
        plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_bias.png", bbox_inches='tight')
        plt.close()

        # plot mae
        plt.figure()
        mae = (y_pred - y_test).abs().mean()
        mae_da = (forecast_series - target_series).abs().mean().values[0]
        plt.plot(mae, label='Intraday MAE')
        plt.axhline(mae_da, color='k', linestyle='--', label='Day-ahead MAE')
        plt.legend()
        plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_mae.png", bbox_inches='tight')
        plt.close()


def main(mae_config, lower_q_run_id, upper_q_run_id, dates: pd.DatetimeIndex, plotting_flag: bool = False, lead_times: dict | None = None):


    plot_path = Path(f"plots/{mae_config.run_id}")
    plot_path.mkdir(parents=True, exist_ok=True)

    if False:
        fig, ax = plt.subplots(1, 1, figsize=(8, 8))
        xlabels = {
            "load": "Load forecast error [MW]",
            "Wind Onshore": "Wind power forecast error [MW]",
        }
        pretty_name_dict = {
            "load": "Load",
            "Wind Onshore": "Onshore Wind",
        }
        error_type = "load"
        total_error = total_error_dict[error_type]
        plot_error_histogram(ax, total_error/1000, plot_path, xlabel=xlabels[error_type], lead_times=['1', '8'], xlim=(-1, 1))
        # set colors of the histogram lines

        # remove labels and ticks
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.set_yticks([])
        ax.set_yticklabels([])
        ax.set_xticks([])
        ax.set_xticklabels([])


        # axes[1].tick_params(labelleft=False)
        legend = ax.get_legend()
        # set legend title and line label size to 36
        if legend is not None:
            legend.set_title("Lead time [h]", prop={"size": 36})
            for text in legend.get_texts():
                text.set_fontsize(36)
        
        plt.savefig(f"{plot_path}/error_histogram_sketch.pdf", bbox_inches="tight")
        plt.close()
    pretty_name_dict = {
            "load": "Load",
            "Wind Onshore": "Onshore Wind",
        }

    if True:
        for error_type in mae_config.error_types:
            for zone in mae_config.zones_error_types[error_type]:
                print(f"Processing zone: {zone}, error type: {error_type}")
                raw_forecast_path = Paths(mae_config.run_id, error_type, zone).raw_forecasts
                y_test_mae, y_pred_mae, scaling_value, target_series, forecast_series = get_data(forecast_output_path=raw_forecast_path)
                y_pred_mae.columns = y_pred_mae.columns.astype(int)
                y_test_mae.columns = y_test_mae.columns.astype(int)
                y_test_q_lower, y_pred_q_lower, _, _, _ = get_data(forecast_output_path=Paths(lower_q_run_id, error_type, zone).raw_forecasts)
                y_pred_q_lower.columns = y_pred_q_lower.columns.astype(int)
                # y_test_q_lower.columns = y_test_q_lower.columns.astype(int)
                y_test_q_upper, y_pred_q_upper, _, _, _ = get_data(forecast_output_path=Paths(upper_q_run_id, error_type, zone).raw_forecasts)
                y_pred_q_upper.columns = y_pred_q_upper.columns.astype(int)
                # y_test_q_upper.columns = y_test_q_upper.columns.astype(int)

                common_indices = y_pred_mae.index.intersection(y_pred_q_lower.index).intersection(y_pred_q_upper.index)
                y_pred_mae = y_pred_mae.loc[common_indices]
                y_test_mae = y_test_mae.loc[common_indices]
                y_pred_q_lower = y_pred_q_lower.loc[common_indices]
                y_pred_q_upper = y_pred_q_upper.loc[common_indices]

                if lead_times is not None:
                    y_pred_mae = y_pred_mae[lead_times[error_type]]
                    y_test_mae = y_test_mae[lead_times[error_type]]
                    y_pred_q_lower = y_pred_q_lower[lead_times[error_type]]
                    y_test_q_lower = y_test_q_lower[lead_times[error_type]]
                    y_pred_q_upper = y_pred_q_upper[lead_times[error_type]]
                    y_test_q_upper = y_test_q_upper[lead_times[error_type]]

                breakpoint()
                if plotting_flag and False:
                    plot_stats(y_test, y_pred, target_series, forecast_series, config, zone, error_type)

            # pred_dict = get_correct_time_indices(y_pred_dict, target_series.index, config.max_lead_time)
                if True:
                    for date in dates:
                        try:
                            gate_forecasts = compile_gate_forecasts(
                                y_pred=y_pred,
                                target_series=target_series,
                                forecast_series=forecast_series,
                                date=date,
                            )
                        except KeyError as e:
                            print(f"KeyError for date {date} in zone {zone}, error_type {error_type}: {e}")
                            continue
                        gate_forecasts.to_csv(Paths(mae_config.run_id, error_type, zone).market_forecasts / f"{date.day}_{date.month}_{date.year}.csv")
                        if False:
                            if date.day == 5 and date.month == 1 and zone == 'NO_3' and error_type == 'Wind Onshore':
                                from src.plotting.plotting_config import set_plt_settings
                                colors = {
                                    'DA': "grey",
                                    'ID2': "#90353b",
                                    'ID3': "#55752f",
                                    'CID': "#e37e00",
                                    'BE': "k",
                                }
                                n_lags = 8
                                set_plt_settings()
                                plt.figure()
                                plt.plot(gate_forecasts.index, gate_forecasts['DA'], label='DA', color=colors['DA'], linewidth=2)
                                # plt.plot(gate_forecasts.index, gate_forecasts['ID1'], label='IDA 1')
                                plt.xlabel('Delivery hour [h]')
                                plt.ylabel('Wind power forecast [MW]')
                                plt.xticks(gate_forecasts.index[::3], [f"{hr}" for hr in gate_forecasts.index.hour[::3]])

                                plt.plot(gate_forecasts.index[:n_lags-1], gate_forecasts['ID2'][:n_lags-1], label='IDA 2', color=colors['ID2'])
                                plt.plot(gate_forecasts.index[12:12+n_lags-1], gate_forecasts['ID3'][12:12+n_lags-1], label='IDA 3', color=colors['ID3'])
                                plt.plot(gate_forecasts.index, gate_forecasts['CID'], label='CID', color=colors['CID'])
                                plt.plot(gate_forecasts.index, gate_forecasts['BE'], label='Actual', color=colors['BE'], linestyle='--')
                                plt.legend()
                                plt.xlim(date, date + pd.Timedelta(hours=23))
                                figdir = Path(f"plots")
                                Path.mkdir(figdir, parents=True, exist_ok=True)
                                plt.savefig(figdir / f"gate_forecasts_{date.day}_{date.month}_{date.year}.pdf", bbox_inches='tight')
                                plt.close()
            
                        
  

if __name__ == "__main__":
    dates_2024 = pd.date_range(start="2024-01-01", end="2024-12-31", freq="D", tz='UTC')

    
    mae_config_yaml_name = 'nordic_mae.yaml'
    mae_config = Config(mae_config_yaml_name)

    mae_config.run_id = sys.argv[1] if len(sys.argv) > 1 else "default_run"
    main(
        mae_config=mae_config, 
        lower_q_run_id="nordic_nn30", 
        upper_q_run_id="nordic_nn70",
        dates=dates_2024,
        plotting_flag=True,
        lead_times={'Wind Onshore': range(1, 5),
                        'load': range(1, 5)},          
        )
    

