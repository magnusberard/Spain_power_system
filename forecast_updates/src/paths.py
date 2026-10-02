

from pathlib import Path


class BasePaths:
    RAW_FORECASTS = "output/raw_forecasts"
    MARKET_FORECASTS = "output/market_forecasts"
    POWERVISION_DATA = "output/powervision_data"

class Paths:
    PV_ERROR_TYPE_NAME_DICT = {"load": "load", "Wind Onshore": "onshore-wind", "Solar": "solar"}
    PV_ZONE_NAME_DICT = {'NO_1': 'NO1', 'NO_2': 'NO2', 'NO_3': 'NO3', 'NO_4': 'NO4', 'NO_5': 'NO5', 'DK_1': 'DANM-VEST', 'ES': 'ES'}

    def __init__(self, run_id: str, error_type: str, zone: str):
        self.raw_forecasts = Path(BasePaths.RAW_FORECASTS) / run_id / error_type / zone
        self.market_forecasts = Path(BasePaths.MARKET_FORECASTS) / run_id / error_type / zone
        self.powervision_data = Path(BasePaths.POWERVISION_DATA) / run_id / self.PV_ERROR_TYPE_NAME_DICT[error_type] / self.PV_ZONE_NAME_DICT[zone]

        self.raw_forecasts.mkdir(parents=True, exist_ok=True)
        self.market_forecasts.mkdir(parents=True, exist_ok=True)
        self.powervision_data.mkdir(parents=True, exist_ok=True)