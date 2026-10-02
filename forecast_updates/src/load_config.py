
import os  # [Spain_power_system]
import yaml

class Config:
    def __init__(self, yaml_file_name):
        self.yaml_file_name = yaml_file_name
        # [Spain_power_system] Resolve configs/ next to this package, not the
        # working directory: run_spain.py works from a data folder outside the repo.
        self.config_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'configs', yaml_file_name)
        
        with open(self.config_file_path) as f:
            config = yaml.safe_load(f)

        self.run_id = config.get('run_id', None)
        self.generation_error_types: list[str] = config.get('generation_error_types', [])
        self.get_load_error_flag: bool = config.get('get_load_error_flag', True)
        self.error_types: list[str] = config.get('generation_error_types', [])
        if self.get_load_error_flag:
            self.error_types.append('load')

        self.zones_error_types: dict[str, list[str]] = config.get('zones_error_types', None)
        self.years: list[int] = config.get('years', None)

        self.forecasting_model: str = config.get('forecasting_model', 'LSTM')
        self.forecasting_model_static: str = config.get('forecasting_model_static', 'LINEAR')
        self.fitting_function: str = config.get('fitting_function', 'asymptotic')
        self.train_test_split: float = config.get('train_test_split', None)
        self.n_lags: int = config['n_lags']
        self.training_params: dict = config.get('training_params', {})
        if self.training_params is None:
            self.training_params = {}
        self.max_lead_time: int = config['max_lead_time']
        self.lead_time_range: range | list[int] = range(1, self.max_lead_time + 1)

    def __repr__(self):
        # print all attributes in a readable format
        return f"Config({self.yaml_file_name}): " + "\n".join(f"{k}={v}" for k, v in self.__dict__.items() if k != 'config_file_path')

    def to_txt(self, output_path: str) -> None:
        """Save the current configuration to a text file."""
        with open(output_path, 'w') as f:
            f.write(self.__repr__())