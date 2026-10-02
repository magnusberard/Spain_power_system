import matplotlib.pyplot as plt
from pathlib import Path
import pandas as pd
from src.paths import Paths
from src.load_config import Config
from src.post_process import (
    normalize_to_day_ahead,
    load_omie_data,
    convert_to_omie
)
from src.utils import make_dir

config = Config('spain.yaml')
config.run_id = "spain_linear"
dates = pd.date_range("01-01-2024", "31-12-2024")



for date in dates:

                            
    date = pd.to_datetime(date)
    day = date.day
    month = date.month
    year = date.year
    for error_type in ["load", "Solar", "Wind Onshore"]:
        for zone in ["ES"]:
            data_path = Paths(config.run_id, error_type, zone).market_forecasts / f"{day}_{month}_{year}.csv"
            
            try:
                gate_forecasts = pd.read_csv(data_path, index_col=0, parse_dates=True)
            except FileNotFoundError:
                print(f"File not found: {data_path}")
                continue


            if True:  
                plt.figure()
                plt.plot(gate_forecasts.index, gate_forecasts['DA'], label='DA/ENTSO-E')
                # plt.plot(gate_forecasts.index, gate_forecasts['ID1'], label='IDA 1')
                plt.plot(gate_forecasts.index, gate_forecasts['ID2'], label='IDA 2')
                plt.plot(gate_forecasts.index[gate_forecasts['ID3'].index.hour >= 12], gate_forecasts['ID3'][gate_forecasts['ID3'].index.hour >= 12], label='IDA 3')
                plt.plot(gate_forecasts.index, gate_forecasts['CID'], label='CID')
                plt.plot(gate_forecasts.index, gate_forecasts['BE'], label='Actual')
                plt.legend()

                plt.savefig(f"plots/{error_type}_example_{day}_{month}_{year}.png")

                plt.close()
            make_dir(f"output/{config.run_id}/{zone}/{error_type}")
            make_dir(f"gates_forecast/{config.run_id}/{zone}/{error_type}")

            if True:
                if error_type == 'Solar':
                    omie_ser = load_omie_data(error_type, day, month, year)
                    
                    diff_with_omie = gate_forecasts['DA'] - omie_ser.values
                    gate_forecasts = gate_forecasts.subtract(diff_with_omie.values, axis=0)
                    
                gate_forecasts[gate_forecasts < 1e-5] = 0.0
                
                norm_gates_forecasts = normalize_to_day_ahead(gate_forecasts)
                
                output_path = Path(f"normalized_forecasts/{config.run_id}/{zone}/{error_type}")
                if not output_path.exists():
                    output_path.mkdir(parents=True, exist_ok=True)

                norm_gates_forecasts.to_csv(output_path / f"{day}_{month}_{year}.csv")

                # omie_ser = load_omie_data(error_type, day, month, year)
                # breakpoint()
                # gates_forecasts, error_term = convert_to_omie(gates_forecasts, omie_ser)

                

                # zero_mask = (gate_forecasts < 1e-5).all(axis=1)
                # omie_ser_values = omie_ser.loc[zero_mask]
                # omie_broadcasted_df = pd.concat([
                #     omie_ser_values.copy() for forecast_hr in range(gate_forecasts.shape[1])
                # ], axis=1)
                # gate_forecasts.loc[zero_mask] = omie_broadcasted_df.values
                
            # gate_forecasts.to_csv(f"output/{config.run_id}/{zone}/{error_type}/{day}_{month}_{year}.csv")
            # error_term_ser = pd.Series(error_term, index=gate_forecasts.index)
            # folder_error_term = f"output/{config.run_id}/{zone}/{error_type}/error_term/"
            # make_dir(folder_error_term)
            # error_term_ser.to_csv(f"{folder_error_term}/error_term_{day}_{month}_{year}.csv")
            # breakpoint()
            # cid_forecast = pd.Series(index=gate_forecasts.index, dtype=float)
            # for delivery_hour in gate_forecasts.index:
            #     cid_forecast[delivery_hour] = gate_forecasts.loc[delivery_hour, delivery_hour - 1]
            # # breakpoint()
            # gates_forecasts = pd.concat([
            #     gate_forecasts.loc[:, [-12, -9, -2, 10]],
            #     cid_forecast,
            #     gate_forecasts.loc[:, 23]
            # ], axis=1
            # )
            # gates_forecasts.columns = ['DA', 'IDA 1', 'IDA 2', 'IDA 3', 'CID', 'BE']

            # gates_forecasts.to_csv(Paths(config.run_id, error_type, zone).market_forecasts / f"{day}_{month}_{year}.csv")
