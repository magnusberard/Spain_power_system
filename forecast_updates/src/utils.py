import os 
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

def get_api_key():
    # [Spain_power_system] Prefer ENTSOE_TOKEN from the environment, the same
    # variable the repo's entsoe_download/ scripts use, so the token never has
    # to live in a file. Upstream's api_key.venv / ENTSOE_API_KEY still works.
    if os.getenv('ENTSOE_TOKEN'):
        return os.getenv('ENTSOE_TOKEN')
    load_dotenv('api_key.venv')
    api_key = os.getenv('ENTSOE_API_KEY')
    return api_key

def make_dir(path):
    """
    Create a directory if it does not exist.
    """
    if not os.path.exists(path):
        os.makedirs(path)


def convert_index_to_datetime(ser):
    ser.index = pd.to_datetime(ser.index, utc=True)
    return ser

def get_hourly(ser, set_hour_indices=True):
    selection = ser.loc[ser.index.minute == 0]
    if set_hour_indices:
        selection.index = selection.index.hour
    return selection

def select_day(ser, year, month, day, timezone="Europe/Madrid"):
    ser_tz = ser.copy()
    ser_tz.index = ser_tz.index.tz_convert(ZoneInfo(timezone))

    return ser_tz.loc[(ser_tz.index.year == year) & (ser_tz.index.month == month) & (ser_tz.index.day == day)]


def validate_day_indexing(df):
    if df.index.size != 24:
        raise ValueError("Forecast DataFrame does not have 24 entries for the selected day.")
    if (df.index.hour != np.arange(24)).any():
        raise ValueError("Forecast DataFrame does not have correct hourly indices for the selected day.")


    