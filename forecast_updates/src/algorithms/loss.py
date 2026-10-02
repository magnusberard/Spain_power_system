import tensorflow as tf


def get_quntile_loss(quantile: float):
    def loss(y_true, y_pred):
        error = y_true - y_pred
        return tf.reduce_mean(
            tf.maximum(quantile * error, (quantile - 1) * error)
        )
    return loss

def get_loss(loss_spec: str = 'mse'):
    """
    Args:
        loss_spec (str): Loss function specification. Options:
            - 'mse': Mean Squared Error
            - 'mae': Mean Absolute Error
            - 'quantile_XX': Quantile loss for quantile XX (e.g., 'quantile_90' for 90th percentile)
    Returns:
        Loss function callable
    """
    loss_spec = loss_spec.lower()
    
    if loss_spec == 'mse' or loss_spec == 'mae':
        return loss_spec
    elif loss_spec.split('-')[0].lower() == 'quantile':
        try:
            quantile = 0.01 * float(loss_spec.split('-')[1])
            if not (0 < quantile < 100):
                raise ValueError
            return get_quntile_loss(quantile)
        except (IndexError, ValueError):
            raise ValueError(
                "Quantile loss specification must be in the format 'quantile_XX' "
                "where XX is a float between 0 and 100 (e.g., 'quantile_90')."
            )
        

    else:
        raise ValueError(
            f"Unknown loss specification: '{loss_spec}'. "
            "Supported: 'mse', 'mae', 'quantile-XX"
        )
    


class RMSELoss(tf.keras.losses.Loss):
    """Custom RMSE loss function."""
    
    def call(self, y_true, y_pred):
        return tf.sqrt(tf.reduce_mean(tf.square(y_true - y_pred)))
