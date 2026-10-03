import unittest

from app.main import create_app


class ApiFoundationTests(unittest.TestCase):
    def test_health_contract(self):
        app = create_app()
        route = next(route for route in app.routes if route.path == "/api/health")
        response = route.endpoint()
        self.assertEqual(response["status"], "ok")
        self.assertIn("schema_version", response)


if __name__ == "__main__":
    unittest.main()
