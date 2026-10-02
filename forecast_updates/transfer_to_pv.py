import pandas as pd
from pathlib import Path
import numpy as np
import sys

from src.load_config import Config
from src.paths import Paths

def prepare_for_powervision(error_type, zone, market_forecasts_path:Path, output_path:Path, 
                            gates=['DA', 'ID2', 'ID3', 'continuous', 'zonal_balancing']):
    output_path.mkdir(parents=True, exist_ok=True)

    dates_2024 = pd.date_range(start="2024-01-01", end="2024-12-29", freq="D")


    weeks = np.arange(1, 53)
    weeks_data = {week: [] for week in weeks}
    # count days in weeks
    for week in weeks:
        days_in_week = sum(1 for date in dates_2024 if date.week == week)
        if days_in_week != 7:
            print(f"Week {week} has {days_in_week} days.")

    for i, date in enumerate(dates_2024):
        try:
            
            df = pd.read_csv(market_forecasts_path / f"{date.day}_{date.month}_{date.year}.csv", index_col=0)
            df.index = range(24)
        except FileNotFoundError:
            breakpoint()
            print(f"File not found for date {date}: {date.day}_{date.month}_{date.year}.csv, for error type {error_type} and zone {zone}. Filling with zeros.")
            # continue
            df = pd.DataFrame(np.zeros((24, len(gates))), columns=gates)
        capacity = pd.read_csv(f"data/input_entsoe/mean_capacities/{error_type.replace(' ', '_')}/{zone}.csv", index_col=0).values[0][0]
        norm_df = df / capacity
        norm_df.columns = gates
        # breakpoint()
        # norm_df.loc[:12, 'ID3'] = norm_df.loc[:12, 'ID2'] 
        norm_df = (norm_df.T - norm_df['DA']).T

        norm_df.index = norm_df.index + len(weeks_data[date.week]) * 24
        weeks_data[date.week].append(norm_df)

            
    for week, week_data in weeks_data.items():
        pd.concat(week_data).to_csv(output_path / f"week_{week}.csv")


if __name__ == "__main__":
    config_name = "nordic.yaml"

    # load config
    config = Config(config_name)
    config.run_id = sys.argv[1] if len(sys.argv) > 1 else "default_run"

    for error_type, zones in config.zones_error_types.items():
        for zone in zones:
            output_path = Paths(config.run_id, error_type, zone).powervision_data
            market_forecasts_path = Paths(config.run_id, error_type, zone).market_forecasts
            prepare_for_powervision(error_type=error_type, zone=zone, market_forecasts_path=market_forecasts_path, output_path=output_path)