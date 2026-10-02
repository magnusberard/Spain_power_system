
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
import yaml
from sklearn.metrics import root_mean_squared_error
from scipy.optimize import curve_fit

from src.load_saved_data import (
    load_load_data,
    load_generation_data,
)

from entsoe import EntsoeRawClient
from src.utils import get_api_key
from src.load_config import Config
from src.entsoe_data_imports import (
    get_generation,
    get_wind_solar_forecast,
    get_load_and_forecast,
    get_capacities,
    get_wind_solar_intraday_forecast
)


def get_entsoe_data(
        config_yaml_name: str,
        ):

    config = Config(config_yaml_name)
    api_key = get_api_key()

    client = EntsoeRawClient(api_key=api_key)
    cap = {}
    carrier = "Wind Onshore"
    psr_dict = {
        "Wind Onshore": "B19",}
    zones = config.zones_error_types[carrier]
    for zone in zones:
        for year in config.years:
            start_ts = pd.Timestamp(f'{year}0101', tz='Europe/Brussels')
            end_ts = pd.Timestamp(f'{year+1}0101', tz='Europe/Brussels')
            
            data = client.query_installed_generation_capacity(country_code=zone, start=start_ts, end=end_ts, psr_type="B19")

            
            import xml.etree.ElementTree as ET
            tree = ET.ElementTree(ET.fromstring(data))
            root = tree.getroot()

            ns = {
                "ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"
            }
            created = root.find("ns:createdDateTime", ns).text
            start = root.find("ns:time_Period.timeInterval/ns:start", ns).text
            end = root.find("ns:time_Period.timeInterval/ns:end", ns).text

            for ts in root.findall("ns:TimeSeries", ns):
                # zone_code = ts.find("ns:inBiddingZone_Domain.mRID", ns).text
                psr_type = ts.find("ns:MktPSRType/ns:psrType", ns).text
                unit = ts.find("ns:quantity_Measure_Unit.name", ns).text

                # print(f"Zone: {zone_code}, PSR: {psr_type}, Unit: {unit}")
                for period in ts.findall("ns:Period", ns):
                    resolution = period.find("ns:resolution", ns).text
                    start = period.find("ns:timeInterval/ns:start", ns).text
                    end = period.find("ns:timeInterval/ns:end", ns).text

                    for point in period.findall("ns:Point", ns):
                        position = int(point.find("ns:position", ns).text)
                        quantity = float(point.find("ns:quantity", ns).text)

                        cap[year] = quantity
        pd.Series(cap).to_csv(f'data/input_entsoe/capacities/{carrier.replace(' ', '_')}/{zone}.csv')
        # print(data['Hydro Run-of-river and poundage'])
    # get_generation(client, zones, years)  # Get generation data for all carriers for the specified zones and years
    # get_wind_solar_forecast(client, zones, years, carriers=generation_error_types)

    # get_wind_solar_intraday_forecast(client, zones, years, carrier='Wind Onshore')

    # get_load_and_forecast(client, load_zones, years)
    # for generator_error_type, zones in config.zones_error_types.items():
    #     get_capacities(client, zones=zones, years=config.years, carrier=generator_error_type)

    

# def get_entsoe_data(
#         config_yaml_name: str,
#         ):

#     config = Config(config_yaml_name)
#     api_key = get_api_key()

#     client = EntsoeRawClient(api_key=api_key)
#     cap = {}
#     carrier = "Wind Onshore"
#     psr_dict = {
#         "Wind Onshore": "B19",}
#     zones = config.zones_error_types[carrier]
#     for zone in zones:
#         for year in config.years:
#             start_ts = pd.Timestamp(f'{year}0101', tz='Europe/Brussels')
#             end_ts = pd.Timestamp(f'{year+1}0101', tz='Europe/Brussels')
            
#             data = client.query_installed_generation_capacity(country_code=zone, start=start_ts, end=end_ts, psr_type="B19")

            
#             import xml.etree.ElementTree as ET
#             tree = ET.ElementTree(ET.fromstring(data))
#             root = tree.getroot()

#             ns = {
#                 "ns": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"
#             }
#             created = root.find("ns:createdDateTime", ns).text
#             start = root.find("ns:time_Period.timeInterval/ns:start", ns).text
#             end = root.find("ns:time_Period.timeInterval/ns:end", ns).text

#             for ts in root.findall("ns:TimeSeries", ns):
#                 # zone_code = ts.find("ns:inBiddingZone_Domain.mRID", ns).text
#                 psr_type = ts.find("ns:MktPSRType/ns:psrType", ns).text
#                 unit = ts.find("ns:quantity_Measure_Unit.name", ns).text

#                 # print(f"Zone: {zone_code}, PSR: {psr_type}, Unit: {unit}")
#                 for period in ts.findall("ns:Period", ns):
#                     resolution = period.find("ns:resolution", ns).text
#                     start = period.find("ns:timeInterval/ns:start", ns).text
#                     end = period.find("ns:timeInterval/ns:end", ns).text

#                     for point in period.findall("ns:Point", ns):
#                         position = int(point.find("ns:position", ns).text)
#                         quantity = float(point.find("ns:quantity", ns).text)

#                         cap[year] = quantity
#         pd.Series(cap).to_csv(f'data/input_entsoe/capacities/{carrier.replace(' ', '_')}/{zone}.csv')



if __name__ == "__main__":
    get_entsoe_data(config_yaml_name='nordic.yaml')
