import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from ..load_config import Config
from ..forecasting import get_correct_time_indices
from ..forecast_data_handling import get_data

def plot_forecast(
        config_yaml_name: str, 
        lead_times_to_plot: list[int]=None, 
        zones_to_plot: list[str]=None, 
        error_types: list[str]=None,
        day: int= 1,
        month: int=1,
        year: int=2024,
        ):
    config = Config(config_yaml_name)
    ts_start = pd.Timestamp(year=year, month=month, day=day, hour=0, tz='Europe/Oslo')
    ts_end = ts_start + pd.Timedelta(days=1)
    ts_range = pd.date_range(start=ts_start, end=ts_end, freq='h', tz='Europe/Oslo')

    if error_types is None:
        error_types = config.error_types
    for error_type in error_types:
        if zones_to_plot is None:
            zones_to_plot = config.zones_error_types[error_type]
        for zone in zones_to_plot:
            y_test_dict, y_pred_dict, scaling_value, target_series, forecast_series = get_data(
                forecast_pickle_dir=f"data/pickled_forecasts/{config.run_id}",
                zone=zone,
                error_type=error_type
            )
            if lead_times_to_plot is None:
                lead_times_to_plot = list(y_pred_dict.keys())
            target_series = pd.Series(target_series.iloc[:, 0])    
            forecast_series = pd.Series(forecast_series.iloc[:, 0])
            
            pred_dict = get_correct_time_indices(y_pred_dict, target_series.index, config.max_lead_time)

            plt.figure(figsize=(15, 7))
            plt.xlim(ts_start, ts_end)
            plt.plot(target_series.loc[ts_range], label='Actual', color='black', linewidth=2)
            plt.plot(forecast_series.loc[ts_range], label='Day-Ahead Forecast', color='gray', linestyle='--')
            for lead_time in lead_times_to_plot:
                plt.plot(scaling_value * pred_dict[lead_time].loc[ts_range], label=f'Forecast Lead Time {lead_time}h')
            plt.title(f'Forecast vs Actual for Zone: {zone}, Error Type: {error_type}')
            plt.xlabel('Time')
            plt.legend()
            plt.show()

            # plot the forecasts made at a specific lead time
            
            


def plot_forecasts_multiple_dates(
        forecasts_dicts: dict,
        target_dicts: dict,
        da_forecast_dicts: dict,
        zone: str,
        error_types: list[str]=None
    ):
    """

    Args:
        forecasts_dicts (dict): Nested forecast dictionary keyed as
            ``{date_str: {error_type: forecasts_df}}`` where ``forecasts_df``
            contains forecast trajectories by forecast hour (columns) and
            delivery hour (index).
        target_dicts (dict): Nested dictionary keyed as
            ``{date_str: {error_type: target_series}}`` with observed values
            for each date and error type.
        da_forecast_dicts (dict): Nested dictionary keyed as
            ``{date_str: {error_type: da_forecast_series}}`` with day-ahead
            forecast values for each date and error type.
        zone (str): Zone name used in the output figure filename.
        error_types (list[str], optional): Error types to plot. If None,
            uses the keys found in ``forecasts_dicts`` for the first date.
    """
    if error_types is None:
        error_types = list(forecasts_dicts[list(forecasts_dicts.keys())[0]].keys())
    from src.plotting.plotting_config import set_plt_settings

    set_plt_settings()


    y_pos_cbar = 1.035

    fig, all_axes = plt.subplots(
        nrows=len(forecasts_dicts[list(forecasts_dicts.keys())[0]]),
        ncols=2,
        figsize=(20, 6 * len(forecasts_dicts[list(forecasts_dicts.keys())[0]])),
        sharex=True,
        constrained_layout=True,
        
    )

    fig.suptitle(" ")
    # fig.set_constrained_layout_pads(
    #     w_pad=0,        # width padding between subplots
    #     h_pad=0,        # height padding between subplots
    #     hspace=0.03,      # height reserved for text (default is 0.02)
    #     wspace=0,      # width reserved for text (default is 0.02)
    # )

    # fig.subplots_adjust(top=0.95)
    pretty_error_types = {
        'load': 'Load',
        'Wind Onshore': 'Wind Onshore',
        'Solar': 'Solar',
    }
    titlesize = 28
    labelsize = 26
    ticksize = 22




    yticks = {
            0: [2, 5, 8],
            1: [0, 10, 20],
            2: [20, 24, 28, 32]
    }
    yrange = {
        0: (1.5, 9),
        1: (0, 20),
        2: (19, 33.5)
    }
    for j, (date_str, forecast_dict) in enumerate(forecasts_dicts.items()):
        axes = all_axes[:, j]
        target_dict = target_dicts[date_str]
        da_forecast_dict = da_forecast_dicts[date_str]
        all_axes[0, j].set_title(date_str, fontsize=labelsize)
        for i, (error_type, forecasts_df) in enumerate(forecast_dict.items()):
            ax = axes[i]
            target_sel = target_dict[error_type]
            da_forecast_sel = da_forecast_dict[error_type]
            forecasts = forecasts_df.iloc[:, 2:]

            cmap = plt.get_cmap('viridis')
            all_forecast_hours = [float(c) for c in forecasts.columns]
            colors = cmap(np.linspace(0, 1, len(forecasts.columns)))

            for col, color in zip(forecasts.columns, colors):
                ser = forecasts[col].loc[forecasts[col].index > float(col)]
                if ser.empty:
                    continue
                ax.plot(ser.index, ser/1000, color=color)

            ax.plot(target_sel.index.hour, target_sel/1000, color='k', linewidth=2.5, label='Actual', linestyle='--')
            ax.plot(da_forecast_sel.index.hour, da_forecast_sel/1000, label='DA', linestyle='--', color='red', linewidth=2.5)
            if j == 0:
                ax.set_ylabel(f"{pretty_error_types[error_type]} [GW]", fontsize=labelsize)
                ax.set_yticks(yticks[i], yticks[i],fontsize=ticksize)
            else:
                ax.set_yticks(yticks[i], yticks[i], fontsize=ticksize)
                ax.set_yticklabels([])
            ax.set_ylim(yrange[i])

        axes[-1].set_xlabel("Delivery hour", fontsize=labelsize)
        ticks = np.arange(0, 24, 6)
        axes[-1].set_xticks(ticks, ticks, fontsize=ticksize)
        axes[-1].set_xlim((0, 23))

    # Set up colorbar
    vmin, vmax = -2, 23
    norm = plt.Normalize(vmin=vmin, vmax=vmax)
    cmap = plt.get_cmap("viridis")
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])


    # Convert data coords (-2 to 23) to figure coords using first axis
    ax0 = all_axes[0, 0]

    fig.canvas.draw()  # Ensure all layout is done

    x0_disp = ax0.transData.transform((vmin, 0))[0]
    x1_disp = ax0.transData.transform((vmax, 0))[0]
    fig_width_disp = fig.bbox.width

    x0_fig = x0_disp / fig_width_disp
    x1_fig = x1_disp / fig_width_disp


    # Add colorbar axes exactly aligned with data range
    cbar_ax = fig.add_axes([x0_fig, y_pos_cbar, x1_fig - x0_fig, 0.01])  # [left, bottom, width, height]

    # Use boundaries to make tick spacing exact
    boundaries = np.arange(vmin, vmax + 1)
    cbar = plt.colorbar(
        sm,
        cax=cbar_ax,
        orientation='horizontal',
        boundaries=boundaries,
        ticks=np.arange(-2, 24, 4),  # align with x-axis ticks
        spacing='proportional',
    )

    cbar.set_label("Forecast hour", fontsize=labelsize)




    ax0.legend(bbox_to_anchor=(0, 1), loc='upper left', fontsize=labelsize)
    # ax0.set_title(f"Forecasts for {error_type} on {day}/{month}/{year}")


    # plt.tight_layout(rect=[0, 0, 1, 0.9])  # leave space for the colorbar
    plt.savefig(f'plots/forecasts_{zone}_both_dates.pdf', bbox_inches='tight')