"""
Example usage of the new single-step forecasting function.
This demonstrates how to generate forecasts without observed values.
"""

import pandas as pd
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.forecasting import get_forecasts_single_step_no_observed
from src.load_config import Config
from src.load_saved_data import load_generation_data
from src.forecast_data_handling import save_data


def example_single_step_forecast():
    """
    Example: Generate single-step forecasts for wind energy in Spain.
    
    This forecast uses only:
    - Day-ahead forecast values
    - Calendar/temporal features (hour, day of year, weekend)
    - NO recently observed values
    
    This provides a conservative baseline that doesn't rely on 
    having the most recent actual observations available.
    """
    
    # Configuration
    years = [2023, 2024]
    zone = "NO2"
    carrier = "Wind Onshore"
    config_path = "configs/nordic.yaml"
    
    print("=" * 70)
    print("Single-Step Forecast Without Observed Values")
    print("=" * 70)
    print(f"Zone: {zone}")
    print(f"Carrier: {carrier}")
    print(f"Years: {years}")
    print(f"Model: LinearMultiStepModel (always)")
    print(f"Use Observed Values: False")
    print()
    
    # Load data
    print("Loading input data...")
    input_data = load_generation_data(
        years=years,
        zone=zone,
        folder="data/input_entsoe",
        carrier=carrier
    )
    print(f"  Target series: {len(input_data.target_series)} observations")
    print(f"  DA forecast series: {len(input_data.da_forecast_series)} observations")
    
    # Load configuration
    print(f"\nLoading configuration from {config_path}...")
    config = Config.from_yaml(config_path)
    print(f"  n_lags: {config.n_lags}")
    print(f"  max_lead_time: {config.max_lead_time}")
    print(f"  train_test_split: {config.train_test_split}")
    print(f"  training_params: {config.training_params}")
    
    # Generate forecasts
    print("\nGenerating forecasts...")
    forecast_df = get_forecasts_single_step_no_observed(
        target_series=input_data.target_series,
        da_forecast_series=input_data.da_forecast_series,
        config=config
    )
    
    # Display results
    print(f"\n✓ Forecast generated successfully!")
    print(f"  Shape: {forecast_df.shape}")
    print(f"  Date range: {forecast_df.index[0]} to {forecast_df.index[-1]}")
    print(f"\nFirst 10 forecasts:")
    print(forecast_df.head(10))
    print(f"\nBasic statistics:")
    print(forecast_df['forecast'].describe())
    
    # Optional: Save results
    output_dir = Path("output/single_step_forecast") / f"{zone}_{carrier.replace(' ', '_')}"
    print(f"\nSaving results to {output_dir}...")
    save_data(
        forecast_output_path=output_dir,
        y_test_df=forecast_df.rename(columns={'forecast': '1_step'}),  # Rename to match format
        y_pred_df=forecast_df.rename(columns={'forecast': '1_step'}),
        scaling_value=input_data.target_series.std(),
        target_series=input_data.target_series,
        forecast_series=input_data.da_forecast_series
    )
    print("✓ Results saved!")
    
    return forecast_df


def compare_with_da_forecast():
    """
    Compare the single-step forecast with the day-ahead forecast.
    """
    print("\n" + "=" * 70)
    print("Comparison: Single-Step vs Day-Ahead Forecast")
    print("=" * 70)
    
    # Load data
    input_data = load_generation_data(
        years=[2024],
        zone="ES",
        folder="data/input_entsoe",
        carrier="Wind Onshore"
    )
    
    config = Config.from_yaml("configs/spain.yaml")
    
    # Generate single-step forecast
    single_step_forecast = get_forecasts_single_step_no_observed(
        target_series=input_data.target_series,
        da_forecast_series=input_data.da_forecast_series,
        config=config
    )
    
    # Create comparison DataFrame
    comparison_idx = single_step_forecast.index
    comparison_df = pd.DataFrame({
        'actual': input_data.target_series[comparison_idx],
        'da_forecast': input_data.da_forecast_series[comparison_idx],
        'single_step_forecast': single_step_forecast['forecast'].values
    })
    
    # Calculate errors
    comparison_df['da_mae'] = (comparison_df['actual'] - comparison_df['da_forecast']).abs()
    comparison_df['single_step_mae'] = (comparison_df['actual'] - comparison_df['single_step_forecast']).abs()
    
    print(f"\nMean Absolute Errors:")
    print(f"  DA Forecast: {comparison_df['da_mae'].mean():.2f} MW")
    print(f"  Single-Step Forecast: {comparison_df['single_step_mae'].mean():.2f} MW")
    print(f"  Improvement: {(comparison_df['da_mae'].mean() - comparison_df['single_step_mae'].mean()):.2f} MW")
    
    print(f"\nSample data (first 5 rows):")
    print(comparison_df.head())
    
    return comparison_df


if __name__ == "__main__":
    # Run example
    forecast_df = example_single_step_forecast()
    
    # Optional: Compare with DA forecast
    # comparison_df = compare_with_da_forecast()
