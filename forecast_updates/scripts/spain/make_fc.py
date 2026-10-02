import sys

from src.load_config import Config
from make_forecasts import make_forecast_loop


config_file = 'spain.yaml'
config = Config(config_file)
config.run_id = sys.argv[1] if len(sys.argv) > 1 else "default_run"
# [Spain_power_system] removed a debugging breakpoint() here
# config.error_types = ['Solar', 'load', ]
# config.zones_error_types.pop("Wind Onshore")
# config.use_observed_values = False
# config.training_params['loss'] = 'quantile-50'
config.forecasting_model = 'LINEAR'
# config.generation_error_types = []
# config.error_types = ['load']
make_forecast_loop(config, use_observed_values=True)