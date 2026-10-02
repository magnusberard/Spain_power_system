
from src.plotting.plot_forecast import plot_forecast

def main():
    plot_forecast(
        config_yaml_name='nordic.yaml', 
        lead_times_to_plot=[1,3,8], 
        zones_to_plot=['NO_3'], 
        error_types=['Wind Onshore'],
        day=14,
        month=5,
        )

if __name__ == "__main__":
    main()

