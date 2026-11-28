import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "Order" / "market" / "Place_marketorder.py"
SPEC = importlib.util.spec_from_file_location("place_marketorder", MODULE_PATH)
place_marketorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(place_marketorder)


class IpAuthorizationDenialTests(unittest.TestCase):
    def test_detects_broker_ip_allowlist_error(self):
        message = "Access denied. Your IP [106.51.175.121] is not authorized."

        self.assertTrue(place_marketorder.is_ip_authorization_denial(message))

    def test_does_not_classify_other_order_rejections_as_ip_errors(self):
        self.assertFalse(place_marketorder.is_ip_authorization_denial("Invalid Input Parameters."))
        self.assertFalse(place_marketorder.is_ip_authorization_denial(None))


if __name__ == "__main__":
    unittest.main()
