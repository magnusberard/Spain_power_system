from src.utils import get_hourly
import pandas as pd
import numpy as np


def restructure_forecast_df(target, da_forecast, forecasts_df, n_steps=1):
    """Restructure the forecast DataFrame to prepare for plotting forecast updates in different stages. 
    Ththe forecasts_df must have the same index as the target and da_forecast, so it must have been preprocessed."""
    hourly_forecasts = get_hourly(forecasts_df)
    hourly_forecasts = hourly_forecasts.clip(0)
    hourly_forecasts.columns = (hourly_forecasts.columns / n_steps).astype(int)
    hourly_target = get_hourly(target)
    default_forecast = get_hourly(da_forecast)

    forecast_hours = np.concatenate([np.array([-12, -9]), np.array(range(-2, 24))])

    delivery_hours = range(24)

    # Container for final forecasts
    forecasts_dict = {}

    for forecast_hour in forecast_hours:
        forecast_values = []
        for delivery_hour in delivery_hours:
            # Calculate lead time
            lead_time = delivery_hour - forecast_hour

            if lead_time in hourly_forecasts.columns:
                val = hourly_forecasts.loc[delivery_hour, lead_time]
            elif lead_time <= 0:
                val = hourly_target.loc[delivery_hour]
            else:
                val = default_forecast.loc[delivery_hour]
            forecast_values.append(val)

        forecasts_dict[forecast_hour] = pd.Series(forecast_values, index=delivery_hours)

    # Final forecasts DataFrame
    restructured_forecasts = pd.DataFrame(forecasts_dict)
    return restructured_forecasts


def normalize_to_day_ahead(forecasts_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize forecast updates to the day-ahead forecast."""
    da_forecast = forecasts_df.iloc[:, 0]
    where_zero = da_forecast == 0
    normalized_forecasts = forecasts_df / da_forecast.values[:, None]
    normalized_forecasts[where_zero] = 0.
    return normalized_forecasts



def load_omie_data(error_type: str, day: int, month: int, year: int) -> pd.Series:


    # --- Load the OMIE CSV file ---
    df = pd.read_csv(f"omie_data/{day}-{month}-{year}.csv", sep=";", decimal=",", skiprows=2)
    
    # --- Replace missing or empty values with 0 ---
    df = df.fillna(0)
    df.drop(index=df.index[-1], inplace=True)  # Drop last row if it's a summary or unwanted
    df.replace({r"\.": "", r",": "."}, regex=True, inplace=True)
    numeric_cols = df.columns.drop(["Fecha", "Hora"])
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    # --- Convert Fecha + Hora to datetime ---
    df["Hour"] = df["Hora"] - 1

    # --- Define columns ---
    
    tech_cols = [
        "CARBÓN", "FUEL-GAS", "AUTOPRODUCTOR", "NUCLEAR", "HIDRÁULICA",
        "CICLO COMBINADO", "EÓLICA", "SOLAR TÉRMICA", "SOLAR FOTOVOLTAICA",
        "COGENERACIÓN/RESIDUOS/MINI HIDRA", "ALMACENAMIENTO"
    ]
    import_col = "IMPORTACIÓN INTER. SIN MIBEL"  # can adjust if your file name differs

    # --- Calculate total generation ---
    df["TotalGeneration_MWh"] = df[tech_cols].sum(axis=1)

    # --- Calculate load = generation + net imports ---
    df["load"] = df["TotalGeneration_MWh"] + df[import_col]

    # --- Extract PV and wind for convenience ---
    df["Solar"] = df["SOLAR FOTOVOLTAICA"] + df["SOLAR TÉRMICA"]
    
    df["Wind Onshore"] = df["EÓLICA"]
    
    # --- Select and sort final output ---
    df = df[["Hour", "Wind Onshore", "Solar", "load"]].set_index("Hour")
    return df[error_type].astype(float)

def convert_to_omie(df, omie_ser):
    entsoe_da = df.loc[:, -12]
    error_term = omie_ser.values - entsoe_da.values
    transformed_df = df + error_term[:, None]
    
    if (transformed_df < 0).any().any():
        print("Warning: Negative values found after conversion to OMIE.")
        breakpoint()
    return transformed_df, error_term