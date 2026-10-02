import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.layers import LSTM, Dense, Activation, Input, Concatenate
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import StandardScaler
from .loss import get_loss

class LSTMModel:
    def __init__(self):
        self.model: Model = None

    
    def train(
        self,
        X_seq_train,
        X_future_train,
        y_train,
        lstm_units=32,
        epochs=30,
        learning_rate=0.001,
        lstm_activation='tanh',
        loss='mse',
        verbose=False,
    ):
        loss_fn = get_loss(loss_spec=loss, verbose=verbose)
        # Flatten future inputs
        X_future_train = X_future_train.reshape(X_future_train.shape[0], -1)

        seq_input = Input(shape=(X_seq_train.shape[1], X_seq_train.shape[2]))
        x = LSTM(lstm_units, activation=lstm_activation)(seq_input)

        future_input = Input(shape=(X_future_train.shape[1],))
        x = Concatenate()([x, future_input])

        output = Dense(y_train.shape[1])(x)  # n_lead_time outputs

        self.model = Model(inputs=[seq_input, future_input], outputs=output)

        self.model.compile(
            optimizer=Adam(learning_rate=learning_rate),
            loss=loss_fn,
        )

        history = self.model.fit(
            [X_seq_train, X_future_train],
            y_train,
            epochs=epochs,
            verbose=0,
        )
        losses = history.history['loss']
        if verbose:
            for epoch, loss_val in enumerate(losses, 1):
                print(f"Epoch {epoch}/{epochs}, Loss: {loss_val:.6f}")


    def predict(self, X_seq_test: np.ndarray, X_future_test: np.ndarray) -> np.ndarray:
        X_future_test = X_future_test.reshape(X_future_test.shape[0], -1)
        return self.model.predict([X_seq_test, X_future_test])