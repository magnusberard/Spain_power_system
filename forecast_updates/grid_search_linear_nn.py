import itertools
import sys
from typing import List, Tuple, Dict

from src.load_config import Config
from src.algorithms.get_algorithm import get_train_function
from src.paths import Paths
from src.forecasting import get_forecasts, load_input_data
from src.forecast_data_handling import get_data, save_data


def compute_rmse_for_run(run_id: str, config: Config) -> float:
    """Compute average RMSE across all zones/error types saved under the given run_id."""
    rmses: List[float] = []
    for error_type in config.error_types:
        zones = config.zones_error_types[error_type]
        for zone in zones:
            data_path = Paths(run_id, error_type, zone).raw_forecasts
            y_test, y_pred, _, _, _ = get_data(data_path)
            # RMSE per lead time, then average across lead times
            rmse = (((y_test - y_pred) ** 2).mean() ** 0.5).mean()
            rmses.append(float(rmse))
    # Average RMSE across zones and error types
    return sum(rmses) / len(rmses) if rmses else float('inf')


def run_single_config(config: Config) -> None:
    """Run forecasts for the provided config and save outputs."""
    train_function = get_train_function(config.forecasting_model)
    years = config.years

    for error_type in config.error_types:
        zones = config.zones_error_types[error_type]
        for zone in zones:
            input_data = load_input_data(years, zone, error_type)
            y_test, y_pred = get_forecasts(
                target_series=input_data.target_series,
                da_forecast_series=input_data.forecast_series,
                train_function=train_function,
                training_params=config.training_params,
                n_lags=config.n_lags,
                lead_time_range=range(1, config.max_lead_time + 1),
                train_test_split=config.train_test_split,
                model_name=config.forecasting_model,
            )
            save_data(
                forecast_output_path=Paths(config.run_id, error_type, zone).raw_forecasts,
                y_test_df=y_test,
                y_pred_df=y_pred,
                scaling_value=input_data.scaling_value,
                target_series=input_data.target_series,
                forecast_series=input_data.forecast_series,
            )


def grid_search_linear_nn(
    config_yaml_name: str = 'nordic.yaml',
    learning_rates: List[float] = [1e-2, 1e-3, 1e-4],
    epochs_list: List[int] = [10, 30, 60],
) -> None:
    base_config = Config(config_yaml_name)
    base_config.forecasting_model = 'LINEAR_NN'

    results: List[Tuple[float, int, float]] = []  # (lr, epochs, rmse)

    for lr, epochs in itertools.product(learning_rates, epochs_list):
        run_id = f"linear_nn_lr{lr}_ep{epochs}"
        print(f"\n=== Running config: lr={lr}, epochs={epochs} (run_id={run_id}) ===")
        cfg = Config(config_yaml_name)
        cfg.forecasting_model = 'LINEAR_NN'
        cfg.training_params = {"learning_rate": lr, "epochs": epochs, "loss": "mse"}
        cfg.run_id = run_id

        # Execute forecasts
        run_single_config(cfg)
        # Evaluate RMSE
        rmse = compute_rmse_for_run(run_id, cfg)
        print(f"RMSE for lr={lr}, epochs={epochs}: {rmse:.6f}")
        results.append((lr, epochs, rmse))

    # Sort and display best result
    results_sorted = sorted(results, key=lambda t: t[2])
    best_lr, best_epochs, best_rmse = results_sorted[0]
    print("\n=== Grid Search Results ===")
    for lr, ep, rm in results_sorted:
        print(f"lr={lr:<8g} epochs={ep:<3d} \t RMSE={rm:.6f}")
    print(f"\nBest config: lr={best_lr}, epochs={best_epochs}, RMSE={best_rmse:.6f}")


if __name__ == "__main__":
    # Optional args: custom YAML name
    yaml_name = sys.argv[1] if len(sys.argv) > 1 else 'nordic.yaml'
    grid_search_linear_nn(config_yaml_name=yaml_name)
