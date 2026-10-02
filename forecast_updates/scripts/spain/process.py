import pandas as pd
import sys

from src.load_config import Config
from main import main

dates = pd.date_range(start="2024-01-01", end="2024-12-30", freq="D", tz='Europe/Madrid')

# dates = pd.date_range(start="2024-07-08", end="2024-07-09", freq="D", tz='UTC')

# dates = pd.date_range(start="2024-01-04", end="2024-01-05", freq="D", tz='UTC')
config_yaml_name = 'spain.yaml'
config = Config(config_yaml_name)
config.run_id = sys.argv[1] if len(sys.argv) > 1 else "default_run"
# config.error_types = ['load']
# config.error_types = ['Solar' ]
# config.zones_error_types.pop("Wind Onshore")
# config.zones_error_types.pop("load")
main(config=config, dates=dates,
        plotting_flag=True,
        lead_times_dict={
            'Wind Onshore': range(1, 13),
            'load': range(1, 13),
            'Solar': range(1, 13)
            }
        )