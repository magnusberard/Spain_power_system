import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Input, Concatenate, Dense
from tensorflow.keras.optimizers import Adam
from .loss import get_loss


class LinearNNModel:
    """
    Neural network model with a single linear layer.
    
    This is mathematically equivalent to ARX when minimizing MSE.
    The single Dense layer without activation is equivalent to linear regression.
    """
    
    def __init__(self):
        self.model: Model = None
        

    def train(
        self,
        X_seq_train,
        X_future_train,
        y_train,
        epochs=30,
        learning_rate=0.001,
        loss='mse',
        verbose=False,
    ):
        """
        Train a neural network with a single linear layer.
        
        This is mathematically equivalent to ARX when minimizing MSE.
        The single Dense layer without activation is equivalent to linear regression.
        
        Args:
            X_seq_train: (n_samples, n_lags, n_seq_features) - past sequence data
            X_future_train: (n_samples, n_lead_time, n_future_features) or (n_samples, n_future_features) - future exogenous data
            y_train: (n_samples, n_lead_time) or (n_samples,) - multi-step or single-step targets
            epochs: Number of training epochs
            learning_rate: Learning rate for optimizer
            loss: Loss function specification
            verbose: Whether to print training information
        
        Returns:
            Trained Keras model
        """
        
        loss_fn = get_loss(loss_spec=loss)
        
        # Flatten future inputs
        X_future_train = X_future_train.reshape(X_future_train.shape[0], -1)
        
        # Flatten past sequences
        X_seq_train_flat = X_seq_train.reshape(X_seq_train.shape[0], -1)
        
        # Create inputs
        seq_input = Input(shape=(X_seq_train_flat.shape[1],))
        future_input = Input(shape=(X_future_train.shape[1],))
        
        # Concatenate inputs
        x = Concatenate()([seq_input, future_input])
        
        # Single linear layer (no activation = linear)
        # Handle both multi-step (2D) and single-step (1D) targets
        if y_train.ndim == 1:
            n_outputs = 1
        else:
            n_outputs = y_train.shape[1]
        output = Dense(n_outputs)(x)
        
        self.model = Model(inputs=[seq_input, future_input], outputs=output)
        
        self.model.compile(
            optimizer=Adam(learning_rate=learning_rate),
            loss=loss_fn,
        )
        
        # Reshape y_train to 2D for model.fit if it's 1D
        y_train_fit = y_train.reshape(-1, 1) if y_train.ndim == 1 else y_train
        
        history = self.model.fit(
            [X_seq_train_flat, X_future_train],
            y_train_fit,
            epochs=epochs,
            verbose=0,
        )
        
        losses = history.history['loss']
        if verbose:
            for epoch, loss_val in enumerate(losses, 1):
                print(f"Epoch {epoch}/{epochs}, Loss: {loss_val:.6f}")


    def predict(self, X_seq_test: np.ndarray, X_future_test: np.ndarray) -> np.ndarray:
        X_future_test = X_future_test.reshape(X_future_test.shape[0], -1)
        X_seq_test_flat = X_seq_test.reshape(X_seq_test.shape[0], -1)
        return self.model.predict([X_seq_test_flat, X_future_test])