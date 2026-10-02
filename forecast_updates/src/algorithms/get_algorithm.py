from typing import Callable 
from abc import ABC, abstractmethod
import numpy as np


from .lstm import LSTMModel
from .arx import ARXModel
# from .arx_sep import ARXSepModel
from .linear_nn import LinearNNModel
from .linear import LinearMultiStepModel


class ForecastingModel(ABC):
    @abstractmethod
    def train(self, X_seq_train, X_future_train, y_train):
        pass

    @abstractmethod
    def predict(self, X_seq_test, X_future_test) -> np.ndarray:
        pass


MODEL_MAPPING = {
    "LSTM": LSTMModel,
    "ARX": ARXModel,
    # "ARX_SEP": ARXSepModel,
    "LINEAR_NN": LinearNNModel,
    "LINEAR": LinearMultiStepModel,
}

def get_forecasting_model(
        forecasting_model_name: str
        ) -> ForecastingModel:
    """
    Set the forecasting algorithm based on the provided model name.

    Args:
        forecasting_model (str): Name of the forecasting model to be used.
                                 Supported: 'LSTM', 'ARX', 'LINEAR'

    Returns:
        Callable: The function that implements the specified forecasting algorithm.
    """
    forecasting_model_name = forecasting_model_name.upper()
    if forecasting_model_name in MODEL_MAPPING:
        return MODEL_MAPPING[forecasting_model_name]()
    else:
        raise NotImplementedError(
            f"Forecasting model '{forecasting_model_name}' is not implemented. Supported models: 'LSTM', 'ARX', 'LINEAR', 'SARIMAX'"
        )



