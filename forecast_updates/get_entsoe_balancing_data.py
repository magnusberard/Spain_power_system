from entsoe import EntsoePandasClient
from dotenv import load_dotenv
import os 
import pandas as pd



def get_balancing_data(zone, year=2024):
    load_dotenv('api_key.venv')
    api_key = os.getenv('ENTSOE_API_KEY')
    years = [2024]
    zones = ['NO_1']

    carriers = [
        'Wind Onshore', 
        # 'Solar'
        ]
    start_ts = pd.Timestamp(f'{year}0101', tz='Europe/Oslo')
    end_ts = pd.Timestamp(f'{year+1}0101', tz='Europe/Oslo')


    client = EntsoePandasClient(api_key=api_key)
    df = client.query_imbalance_volumes(country_code=zone, start=start_ts, end=end_ts)

    return df
    

if __name__ == "__main__":
    zonal_imb_dict = {}
    zonal_imb_dict_t = {}
    if False:
        for zone in ['NO_1']:  
            zonal_imbalance = get_balancing_data(zone)
            zonal_imb_dict_t[zone] = zonal_imbalance
            mean_zonal_imbalance = zonal_imbalance.abs().sum().values[0]
            mean_total_imbalance = zonal_imbalance
            pd.Series(zonal_imbalance.values.flatten(), index=zonal_imbalance.index).to_csv(f'data/entsoe_zonal_imbalance_{zone}_2024.csv')
            zonal_imb_dict[zone] = mean_zonal_imbalance

    zones = ['NO_1', 'NO_2', 'NO_3', 'NO_4', 'NO_5']
    # load data
    for zone in zones:
        zonal_imb_dict[zone] = pd.read_csv(f'data/entsoe_zonal_imbalance_{zone}_2024.csv', index_col=0, parse_dates=True)['0']

    imb_data = pd.DataFrame(zonal_imb_dict)
    total_national_imbalance = imb_data.sum(axis=1).abs().sum() # 8.45 GWh / day 
    zonal_imb = imb_data.abs().sum() 
    total_imb = zonal_imb.sum()    # 14.46 GWh / day
    
    print("Total national imbalance:", total_national_imbalance / (1000 * 365))
    print("Total imbalance across zones:", total_imb / (1000 * 365))
    print("Zonal imbalance: ")
    for zone, imb in zonal_imb.items():
        print(f"{zone}: {imb / (1000 * 365)}")
    zonal_imb.to_csv('data/entsoe_zonal_imbalance_2024.csv')