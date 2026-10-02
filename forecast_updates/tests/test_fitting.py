import unittest
from src.fitting import calc_fitting_params_loop
from src.load_config import ConfigSettings

class TestFittingParams(unittest.TestCase):
    def test_calc_fitting_params_loop(self):
        config = ConfigSettings("spain.yaml")
        calc_fitting_params_loop(config)
        # You might add assertions here later
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":

    TestFittingParams.test_calc_fitting_params_loop()