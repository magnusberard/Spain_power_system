
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import sys 
from zoneinfo import ZoneInfo

from src.plotting.plotting_config import PLOTTING_PARAMS, set_plt_settings
from src.paths import Paths
from src.load_config import Config
from src.fitting import calc_fitting_params_loop
from src.utils import convert_index_to_datetime, select_day, validate_day_indexing
from src.forecasting import get_correct_time_indices
from src.forecast_data_handling import get_data
from src.post_process import restructure_forecast_df, normalize_to_day_ahead, load_omie_data, convert_to_omie
from src.utils import make_dir

def define_gate_times(date: pd.Timestamp, tz='Europe/Madrid') -> tuple[dict, dict]:
    gate_time_dict = {
            "DA": date - pd.Timedelta(hours=12),  # DA
            # "ID1": date - pd.Timedelta(hours=9),   # IDA 1
            "ID2": date - pd.Timedelta(hours=2),   # IDA 2
            "ID3": date + pd.Timedelta(hours=10),  # IDA 3
            "CID": pd.DatetimeIndex([date + pd.Timedelta(hours=hr) for hr in range(-1, 23)]),  # CID
            # "BE": pd.DatetimeIndex([date + pd.Timedelta(hours=hr) for hr in range(24)])  # BE
        }

    all_delivery_hours = pd.date_range(start=date, periods=24, freq='h', tz=tz)
    second_half_delivery_hours = all_delivery_hours[12:]

    delivery_hours = {
        "DA": all_delivery_hours,
        # "ID1": all_delivery_hours,
        "ID2": all_delivery_hours,
        "ID3": second_half_delivery_hours,
        "CID": all_delivery_hours,
        "BE": all_delivery_hours
    }
    return gate_time_dict, delivery_hours, all_delivery_hours


# def compile_gate_forecasts_from_restructured(
#         y_pred: pd.DataFrame,
#         target_series: pd.Series,
#         forecast_series: pd.Series,
#         date: pd.Timestamp,
# ):
#     """Compile gate forecasts from restructured y_pred, which has already index delivery_time (instead of forecast time)

#     Args:
#         y_pred (pd.DataFrame): _description_
#         target_series (pd.Series): _description_
#         forecast_series (pd.Series): _description_
#         date (pd.Timestamp): _description_
#     """
#     gate_time_dict, delivery_hours, all_delivery_hours = define_gate_times(date)
    
#     df = pd.DataFrame(index=all_delivery_hours, columns=gate_time_dict.keys(), dtype=float)
#     for gate_name, gate_time in gate_time_dict.items():
#         gate_delivery_hours = delivery_hours[gate_name]
#         # y_pred.loc[gate_delivery_hours]


def compile_gate_forecasts(
        y_pred: pd.DataFrame,
        target_series: pd.Series,
        forecast_series: pd.Series,
        date: pd.Timestamp,
    ) -> pd.DataFrame:

    gate_time_dict, delivery_hours, all_delivery_hours = define_gate_times(date, tz=date.tz)
    
    gate_forecasts = pd.DataFrame(index=all_delivery_hours, columns=gate_time_dict.keys(), dtype=float)

    for gate_name, gate_time in gate_time_dict.items():
        gate_delivery_hours = delivery_hours[gate_name]
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
    
    bb = y_pred.loc[y_pred.index.intersection(target_series.index)]
    cc= target_series.loc[y_pred.index.intersection(target_series.index)]

    # plt.hist((bb-cc.values).groupby(bb.index.hour).mean())
    # plt.show()

    # da_forecast_err = forecast_series.loc[y_pred.index] - target_series.loc[y_pred.index]
    # mean_da_forecast_err = da_forecast_err.mean()
    # forecast_err = y_pred.loc[y_pred.index.intersection(target_series.index)] - target_series.loc[y_pred.index.intersection(target_series.index)].values
    # mean_forecast_err = forecast_err.mean()
    # rmse_da = (da_forecast_err.pow(2).mean()) ** 0.5
    # rmse_forecast = (forecast_err.pow(2).mean()) ** 0.5

    # gate_forecasts["DA"] = forecast_series.loc[gate_forecasts.index]
    # fill NaN values with value on the left
    gate_forecasts = gate_forecasts.ffill(axis=1).bfill(axis=1)
    return gate_forecasts


def collect_forecast_errors(config, error_type, lead_times=None) -> dict:
    error_dict = {}
    entsoe_error_dict = {}

    for zone in config.zones_error_types[error_type]:
        raw_forecast_path = Paths(config.run_id, error_type, zone).raw_forecasts
        y_test, y_pred, _, target_series, forecast_series = get_data(forecast_output_path=raw_forecast_path)

        error_df = y_pred - y_test
        if lead_times is not None:
            error_df = error_df[lead_times]
        error_dict[zone] = error_df

        entsoe_error_dict[zone] = forecast_series.iloc[:, 0] - target_series.iloc[:, 0]
        # da_error_dict[zone] = static_y_pred.iloc[:, 0] - static_y_test.iloc[:, 0]
    return error_dict, entsoe_error_dict

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
        palette={1: 'tab:blue', 2: 'tab:orange', 4: 'tab:green', 12: 'tab:red'},
    )
    ax.set_xlim(xlim)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return 

def plot_stats(y_test, y_pred, target_series, forecast_series, config, zone, error_type, test_dates, save_id: str = "", corrected_ypred=None, lead_times=None, no_obs_forecast=None):
        y_pred = y_pred.loc[test_dates]
        y_test = y_test.loc[test_dates]

        target_in_test_period = target_series.loc[test_dates]
        if no_obs_forecast is not None:
            forecast_in_test_period = no_obs_forecast.loc[test_dates]
        
        plt.figure()
        rmse = ((y_test.loc[test_dates] - y_pred.loc[test_dates]) ** 2).mean() ** 0.5
        if corrected_ypred is not None:
            rmse_corrected = ((y_test.loc[test_dates] - corrected_ypred) ** 2).mean() ** 0.5
            plt.plot(rmse_corrected, label='Intraday RMSE Corrected')
        if plot_last_rmse:=True:
            rmse_last = ((y_test.loc[test_dates, 23] - y_pred.loc[test_dates, 23]) ** 2).mean() ** 0.5
            plt.axhline(rmse_last, color='orange', linestyle='-.', label='Intraday RMSE 23h Lead Time')
        if no_obs_forecast is not None and False:
            rmse_no_obs = ((target_in_test_period - forecast_in_test_period) ** 2).mean() ** 0.5
            plt.axhline(rmse_no_obs, color='purple', linestyle='-.', label='Intraday RMSE No Obs')
        rmse_da = (target_series - forecast_series).pow(2).mean() ** 0.5
        plt.plot(rmse, label='Intraday RMSE', color=PLOTTING_PARAMS['carrier_colors'][error_type])
        plt.axhline(rmse_da, color='k', linestyle='--', label='ENTSO-E DA RMSE')
        print(config.run_id)
        print(f"plots/{config.run_id}/{zone}_{error_type}_rmse.png")
        if lead_times is not None:
            plt.xlim((min(lead_times), max(lead_times)))
        else:
            plt.xlim((rmse.index.min(), rmse.index.max()))
        plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_rmse{save_id}.png", bbox_inches='tight')
        plt.close()

        # plot bias
        plt.figure()
        bias = (y_pred - y_test).mean()
        if corrected_ypred is not None:
            bias_corrected = (corrected_ypred - y_test).mean()
            plt.plot(bias_corrected, label='Intraday Bias Corrected')
        if plot_last_bias:=True:
            bias_last = (y_pred.loc[:, 23] - y_test.loc[:, 23]).mean()
            plt.axhline(bias_last, color='orange', linestyle='-.', label='Intraday Bias 23h Lead Time')
        if no_obs_forecast is not None and False:
            bias_no_obs = (forecast_in_test_period - target_in_test_period).mean()
            plt.axhline(bias_no_obs, color='purple', linestyle='-.', label='Intraday Bias No Obs')
        bias_da = (forecast_series - target_series).mean()
        plt.plot(bias, label='Intraday Bias', color=PLOTTING_PARAMS['carrier_colors'][error_type])
        plt.axhline(bias_da, color='k', linestyle='--', label='Day-ahead Bias')
        plt.legend()
        if lead_times is not None:
            plt.xlim((min(lead_times), max(lead_times)))
        else:
            plt.xlim((rmse.index.min(), rmse.index.max()))
        plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_bias{save_id}.png", bbox_inches='tight')
        plt.close()

        # plot mae
        plt.figure()
        mae = (y_pred - y_test).abs().mean()
        mae_da = (forecast_series - target_series).abs().mean()
        if no_obs_forecast is not None:
            mae_no_obs = (forecast_in_test_period - target_in_test_period).abs().mean()
            plt.axhline(mae_no_obs, color='purple', linestyle='-.', label='Intraday MAE No Obs')

        plt.plot(mae, label='Intraday MAE', color=PLOTTING_PARAMS['carrier_colors'][error_type])
        plt.axhline(mae_da, color='k', linestyle='--', label='Day-ahead MAE')
        plt.legend()
        if lead_times is not None:
            plt.xlim((min(lead_times), max(lead_times)))
        else:
            plt.xlim((rmse.index.min(), rmse.index.max()))
        plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_mae{save_id}.png", bbox_inches='tight')
        plt.close()


def plot_rmse(err_dict, da_err_dict, plot_path, error_types, lead_times=None):
    
    plt.figure()
    set_plt_settings()
    for error_type in error_types:
        err = err_dict[error_type]
        da_err = da_err_dict[error_type]

        rmse = (err ** 2).mean() ** 0.5
        rmse.index = rmse.index.astype(int)

        common_index = err.index.intersection(da_err.index)
        entsoe_rmse = (da_err.loc[common_index].pow(2).mean()) ** 0.5
        plt.plot(
            rmse.index,
            rmse.values,
            color=PLOTTING_PARAMS['carrier_colors'][error_type],
            label=f"Intraday {error_type}",
        )
        plt.hlines(
            entsoe_rmse,
            xmin=rmse.index.min(),
            xmax=rmse.index.max(),
            linestyle=':',
            color=PLOTTING_PARAMS['carrier_colors'][error_type],
            label='ENTSO-E DA',
        )

    plt.xlabel("Lead time [h]")
    plt.ylabel("RMSE [MW]")

    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.xticks(lead_times[error_type] if lead_times is not None else rmse.index)
    if lead_times is not None:
        plt.xlim((min(lead_times[error_type]), max(lead_times[error_type])))
    else:
        plt.xlim((rmse.index.min(), rmse.index.max()))

    plt.savefig(plot_path / "rmse_by_lead.pdf", bbox_inches='tight')
    plt.close()

# def plot_zone_rmse_curves(config: Config, lead_times: dict | None = None) -> None:
#     """Plot RMSE vs lead time for each zone separately."""
#     plot_path = Path(f"plots/{config.run_id}")
#     plot_path.mkdir(parents=True, exist_ok=True)

#     for error_type in config.error_types:
#         lt_error_type = lead_times[error_type] if lead_times is not None and error_type in lead_times else None

#         for zone in config.zones_error_types[error_type]:
#             raw_forecast_path = Paths(config.run_id, error_type, zone).raw_forecasts
#             y_test, y_pred, _, target_series, forecast_series = get_data(forecast_output_path=raw_forecast_path)

#             y_pred.columns = y_pred.columns.astype(int)
#             y_test.columns = y_test.columns.astype(int)


#             plot_rmse(y_pred, y_test, target_series, forecast_series, zone, error_type, plot_path, lead_times)
#             # 
#

def restructure_forecasts(y_data, is_test=False):
    """Restructure forecasts from format with lead time as columns and forecast time as index to format with delivery time as index and lead time as columns.

    Args:
        y_data (_type_): _description_

    Returns:
        _type_: _description_
    """
    if is_test:
        assert np.unique(np.diag(y_data.values[::-1])).size == 1, "Expected all values on the same diagonal to be the same, but found different values. Check the input format of y_data."
    lead_times = y_data.columns.astype(int)
    forecast_time = y_data.index
    delivery_time_start = forecast_time[0] + pd.Timedelta(hours=1)
    delivery_time_end = forecast_time[-1] + pd.Timedelta(hours=y_data.columns.astype(int).max())
    delivery_hours = pd.date_range(start=delivery_time_start, end=delivery_time_end, freq='h')
    
    df = pd.DataFrame(index=delivery_hours, columns=lead_times)
    for lead_time in lead_times:
        ser_lt = y_data[lead_time].copy()
        ser_lt.index = ser_lt.index + pd.Timedelta(hours=lead_time)
        df[lead_time] = ser_lt

    df = df.iloc[lead_times.max():df.shape[0] - lead_times.max()]  # drop rows with NaN values (corresponding to delivery times for which we don't have forecasts for all lead times)
    return df


def main(config, dates: pd.DatetimeIndex, plotting_flag: bool = False, lead_times_dict: dict | None = None):
    plot_path = Path(f"plots/{config.run_id}")
    plot_path.mkdir(parents=True, exist_ok=True)
    total_error_dict = {}
    total_da_error_dict = {}
    total_entsoe_error_dict = {}
    for error_type in config.error_types:
        error_dict, entsoe_error_dict = collect_forecast_errors(config, error_type)
        total_error = sum(error_dict.values())
        total_entsoe_error = sum(entsoe_error_dict.values())
        total_error_dict[error_type] = total_error
        total_entsoe_error_dict[error_type] = total_entsoe_error

    # if plotting_flag:
    #     plot_zone_rmse_curves(config=config, lead_times=lead_times)

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
        plot_error_histogram(ax, total_error/1000, plot_path, xlabel=xlabels[error_type], lead_times=['1', '24'], xlim=(-1, 1))
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
    
                
    if True:
        collect_err = {}
        collect_da_err = {}
        collect_correction_terms = {}
        for error_type in config.error_types:
            collect_err[error_type] = []
            collect_da_err[error_type] = []
            collect_correction_terms[error_type] = []
            for zone in config.zones_error_types[error_type]:
                raw_forecast_path = Paths(config.run_id, error_type, zone).raw_forecasts
                y_test, y_pred, scaling_value, target_series, forecast_series = get_data(forecast_output_path=raw_forecast_path)
                y_pred.columns = y_pred.columns.astype(int)
                y_test.columns = y_test.columns.astype(int)
                             
                if isinstance(target_series, pd.DataFrame):
                    target_series = target_series.iloc[:, 0]
                if isinstance(forecast_series, pd.DataFrame):
                    forecast_series = forecast_series.iloc[:, 0]
                test_dates= pd.date_range(start=dates[0], end=dates[-1], freq='h')

                y_test = y_test.reindex(test_dates, fill_value=0)
                y_pred = y_pred.reindex(test_dates, fill_value=0)
                forecast_series = forecast_series.reindex(test_dates, fill_value=0)
                target_series = target_series.reindex(test_dates, fill_value=0)
                y_test = y_test.loc[test_dates]
                y_pred = y_pred.loc[test_dates]
                forecast_series = forecast_series.loc[test_dates]
                target_series = target_series.loc[test_dates]
                correction_term = (y_pred - y_test).mean()
                y_pred -= correction_term
                collect_err[error_type].append(y_test - y_pred)
                collect_da_err[error_type].append(target_series - forecast_series)
                collect_correction_terms[error_type].append(correction_term)
        # make into dataframes
        
        total_err = {}        
        total_da_err = {}
        total_correction_terms = {}
        
        for error_type in config.error_types:
            err = pd.concat(collect_err[error_type])
            err = err.groupby(err.index).sum()  # sum errors across zones for each lead time
            total_err[error_type] = err
            da_err = pd.concat(collect_da_err[error_type])
            da_err = da_err.groupby(da_err.index).sum()  # sum errors across zones for each lead time
            total_da_err[error_type] = da_err
            corr = pd.concat(collect_correction_terms[error_type])
            corr = corr.groupby(corr.index).sum()  
            total_correction_terms[error_type] = corr
        


        plot_rmse(total_err, total_da_err, plot_path, config.error_types, lead_times=lead_times_dict)
        # pretty_name_dict = {
        #     "load": "Load",
        #     "Wind Onshore": "Onshore Wind",
        # }
        # if True:
        #     fig, axes = plt.subplots(1, 2, figsize=(16, 8), sharey=True)
        #     xlabels = {
        #         "load": "Load forecast error [MW]",
        #         "Wind Onshore": "Wind power forecast error [MW]",

        #     }


        #     for i, (error_type, total_error_df) in enumerate(total_err.items()):
        #         plot_error_histogram(axes[i], total_error_df, plot_path, xlabel=xlabels[error_type], lead_times=[1,2,4,12])

        #     # axes[1].tick_params(labelleft=False)
        #     legend = axes[0].get_legend()
        #     if legend is not None:
        #         legend.remove()

        #     plt.savefig(f"{plot_path}/error_histogram.pdf", bbox_inches="tight")
        #     plt.close()

        for error_type in config.error_types:
            for zone in config.zones_error_types[error_type]:
                print(f"Processing zone: {zone}, error type: {error_type}")
                raw_forecast_path = Paths(config.run_id, error_type, zone).raw_forecasts
                y_test, y_pred, scaling_value, target_series, forecast_series = get_data(forecast_output_path=raw_forecast_path)
                y_pred.columns = y_pred.columns.astype(int)
                y_test.columns = y_test.columns.astype(int)
                test_dates= pd.date_range(start=dates[0].tz_convert('Europe/Madrid'), end=dates[-1].tz_convert('Europe/Madrid'), freq='h', tz='Europe/Madrid')

                def timezone_index(df, timezone="Europe/Madrid"):
                    
                    df.index = df.index.tz_convert(ZoneInfo(timezone))
                
                target_series.loc[(target_series.index.month == 12) & (target_series.index.day == 2)].iloc[14:]
                y_test = convert_index_to_datetime(y_test)
                y_pred = convert_index_to_datetime(y_pred)
                target_series = convert_index_to_datetime(target_series)
                forecast_series = convert_index_to_datetime(forecast_series)

                timezone_index(y_test)
                timezone_index(y_pred)
                timezone_index(target_series)
                timezone_index(forecast_series)

                

                

                y_test = y_test.reindex(test_dates, fill_value=0)
                y_pred = y_pred.reindex(test_dates, fill_value=0)

                target_series = target_series.reindex(test_dates, fill_value=0)
                forecast_series = forecast_series.reindex(test_dates, fill_value=0)
                y_test = y_test.loc[test_dates]
                y_pred = y_pred.loc[test_dates]
                y_pred -= (y_pred - y_test).mean()

                
                
                # y_test = restructure_forecasts(y_test, is_test=True)
                # y_pred = restructure_forecasts(y_pred)
                if False:
                    raw_forecast_path_no_obs = Paths("linear_no_obs", error_type, zone).raw_forecasts
                    y_test_no_obs, y_pred_no_obs, scaling_value, target_series, forecast_series = get_data(forecast_output_path=raw_forecast_path_no_obs)
                    y_pred_no_obs.columns = y_pred_no_obs.columns.astype(int)
                    y_test_no_obs.columns = y_test_no_obs.columns.astype(int)
                    lead_time_for_no_obs_forecast = y_pred_no_obs.columns.astype(int).max()
                    y_test_no_obs = y_test_no_obs.loc[test_dates - pd.Timedelta(hours=lead_time_for_no_obs_forecast)]  # shift y_test_no_obs by 24 hours to align with y_pred and y_test
                    y_pred_no_obs = y_pred_no_obs.loc[test_dates - pd.Timedelta(hours=lead_time_for_no_obs_forecast)]  # shift y_pred_no_obs by 24 hours to align with y_test and y_pred
                    y_pred_no_obs -= (y_pred_no_obs - y_test_no_obs).mean()
    
                    


                    y_pred_no_obs_restructured = y_pred_no_obs.loc[:, lead_time_for_no_obs_forecast].copy()
                    y_pred_no_obs_restructured.index += pd.to_timedelta(lead_time_for_no_obs_forecast, unit="h")
                
                # y_test_no_obs = restructure_forecasts(y_test_no_obs, is_test=True)
                # y_pred_no_obs = restructure_forecasts(y_pred_no_obs)

                
             
                if isinstance(target_series, pd.DataFrame):
                    target_series = target_series.iloc[:, 0]
                if isinstance(forecast_series, pd.DataFrame):
                    forecast_series = forecast_series.iloc[:, 0]

                
                err = y_pred - y_test
                y_pred_corrected = y_pred.copy()

                
            
                def calc_cov(yp_cur, yt_cur, yp_last):
                    return np.cov(yp_cur - yt_cur, yp_cur - yp_last)[1,0]

                def calc_correction_factor(yp_cur, yt_cur, yp_last):
                    return calc_cov(yp_cur, yt_cur, yp_last) / np.var(yp_cur - yp_last) 

                last_lead_time = y_pred.columns[-1]


                # da_forecast = y_pred_no_obs_restructured.reindex(y_pred.index, fill_value=0)
                da_forecast = y_pred.loc[:, last_lead_time]
             
                corr_factor = calc_correction_factor(y_pred[last_lead_time], y_test[last_lead_time], da_forecast) 
                # y_pred_corrected.loc[:, last_lead_time] = y_pred[last_lead_time] - corr_factor * (y_pred[last_lead_time] - da_forecast)
                
                corr_factor_ser = pd.Series(corr_factor, index=[last_lead_time])
                for lead_time in y_test.columns[-2::-1]:
                    calc_cov(y_pred[lead_time], y_test[lead_time], y_pred_corrected[lead_time + 1])
                    corr_factor = calc_correction_factor(y_pred[lead_time], y_test[lead_time], y_pred_corrected[lead_time + 1]) 
                    corr_factor_ser[lead_time] = corr_factor
                    y_pred_corrected[lead_time] = y_pred[lead_time] - corr_factor * (y_pred[lead_time] - y_pred_corrected[lead_time + 1])
                print(corr_factor_ser)

                
                # y_test and y_pred can be numpy arrays or pandas objects
                if False:
                    plt.figure()
                    from sklearn.linear_model import LinearRegression
                    colors = plt.get_cmap('tab20').colors
                    
                    color = 'red'  
                    color_corr = 'blue'  
                    plt.scatter(y_test[lead_time], y_pred[lead_time] - y_test[lead_time], s=0.1, label=f"Lead time {lead_time}h", color=color)
                    plt.scatter(y_test[lead_time], y_pred_corrected[lead_time] - y_test[lead_time], s=0.1, label=f"Lead time {lead_time}h, Corrected", color=color_corr)

                    # fit the residuals with a linear regression line
                    lr = LinearRegression()
                    residuals_nonnan = (y_pred_corrected[lead_time] - y_test[lead_time]).dropna()
                    y_test_nonnan = y_test[lead_time].loc[residuals_nonnan.index]

                    lr.fit(y_test_nonnan.values.reshape(-1, 1), residuals_nonnan.values.reshape(-1, 1))
                    x_fit = np.linspace(y_test_nonnan.min(), y_test_nonnan.max(), 100).reshape(-1, 1)
                    y_fit = lr.predict(x_fit)
                    plt.plot(x_fit, y_fit, color=color, label=f'Linear fit lead time {lead_time}h')


                    plt.xlabel("Actual value [MW]")
                    plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_residuals.png", bbox_inches='tight')
                    plt.close()

                # plot a histogram of the y_pred and y_test for lead times 1, and 24. 
                # plt.figure()
                # plt.hist(y_test[8], bins=50, alpha=0.5, label='Actual')
                # plt.hist(y_pred[8], bins=50, alpha=0.5, label='Predicted')
                # plt.xlabel("Value [MW]")
                # plt.legend()
                # plt.savefig(f"plots/{config.run_id}/{zone}_{error_type}_histogram.png", bbox_inches='tight')
                # plt.close()
                lead_times = lead_times_dict[error_type] if lead_times_dict is not None and error_type in lead_times_dict else None
                
                # if lead_times is not None:
                #     y_pred = y_pred[lead_times[error_type]]
                if plotting_flag and True:
                    plot_stats(y_test, y_pred, target_series, forecast_series, config, zone, error_type, test_dates,save_id="", lead_times=lead_times, no_obs_forecast=y_pred.loc[:, 23])


            # pred_dict = get_correct_time_indices(y_pred_dict, target_series.index, config.max_lead_time)
                if True:
                    
                    for date in dates:
                        if (date.day, date.month) not in [(8, 7), (2, 12)]:
                            continue
                        try:
                            gate_forecasts = compile_gate_forecasts(
                                y_pred=y_pred,
                                target_series=target_series,
                                forecast_series=y_pred.loc[:, y_pred.columns.astype(int).max()],
                                date=date,
                            )
                            breakpoint()
                        except KeyError as e:
                            print(f"KeyError for date {date} in zone {zone}, error_type {error_type}: {e}")
                            continue
                        gate_forecasts.to_csv(Paths(config.run_id, error_type, zone).market_forecasts / f"{date.day}_{date.month}_{date.year}.csv")
                        
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
                                n_lags = 12
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
                                figdir = Path(f"plots/{config.run_id}")
                                Path.mkdir(figdir, parents=True, exist_ok=True)
                                plt.savefig(figdir/ f"gate_forecasts_{date.day}_{date.month}_{date.year}.pdf", bbox_inches='tight')
                                plt.close()

                                # sketch version 
                                plt.figure()
                                plt.plot(gate_forecasts.index, gate_forecasts['DA'], color=colors['DA'], linewidth=4)
                                # plt.plot(gate_forecasts.index, gate_forecasts['ID1'], label='IDA 1')
                                plt.xlabel('Hour [h]', fontsize=36)
                                plt.ylabel('Power [MW]', fontsize=36)
                                plt.xticks([], [])
                                plt.yticks([], [])

                                plt.plot(gate_forecasts.index[:n_lags-1], gate_forecasts['ID2'][:n_lags-1], color=colors['ID2'], linewidth=4)
                                plt.plot(gate_forecasts.index[12:12+n_lags-1], gate_forecasts['ID3'][12:12+n_lags-1], color=colors['ID3'], linewidth=4)
                                plt.plot(gate_forecasts.index, gate_forecasts['CID'], color=colors['CID'], linewidth=4)
                                plt.plot(gate_forecasts.index, gate_forecasts['BE'], color=colors['BE'], linestyle='--', linewidth=4)
                                # plt.legend()
                                plt.xlim(date, date + pd.Timedelta(hours=23))
                                figdir = Path(f"plots")
                                Path.mkdir(figdir, parents=True, exist_ok=True)
                                plt.savefig(figdir / f"gate_forecasts_sketch_{date.day}_{date.month}_{date.year}.pdf", bbox_inches='tight')
                                plt.close()
            


if __name__ == "__main__":

    # loop through dates in the year 2024 using pandas
    # Generate all dates in 2024
    dates = pd.date_range(start="2024-01-01", end="2024-12-30", freq="D", tz='Europe/Madrid')
    # dates = pd.date_range(start="2024-01-04", end="2024-01-05", freq="D", tz='UTC')
    config_yaml_name = 'nordic.yaml'
    config = Config(config_yaml_name)
    config.run_id = sys.argv[1] if len(sys.argv) > 1 else "default_run"
    # config.error_types = ['load']
    main(config=config, dates=dates,
            plotting_flag=True,
            lead_times_dict={'Wind Onshore': range(1, 13),
                        'load': range(1, 13)}
            )
    
    # config.run_id = "nordic_lstm"
    # main(config=config, dates=dates_2024,
    #         plotting_flag=True)
    
    # config.run_id = "nordic_linear"
    # main(config=config, dates=dates_2024,
    #         plotting_flag=True)
        # except Exception as e:
        #     print(f"Error processing date {date}: {e}")

    # main(config_yaml_name='nordic.yaml', day=10, month=1, year=2024, plotting_flag=False)
