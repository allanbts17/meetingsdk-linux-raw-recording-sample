import unittest
from app.http_common import create_http_app
from app.models import JoinRequest, PlayRequest, ControlRequest


class OpenApiTests(unittest.TestCase):
    def setUp(self):
        async def authenticate(request):
            return None
        self.app = create_http_app(None, authenticate)
        self.schema = self.app.openapi()

    def test_all_runtime_endpoints_have_documented_responses_and_unique_ids(self):
        expected = {(route.path, method.lower()) for route in self.app.routes
                    if getattr(route, "include_in_schema", False)
                    for method in route.methods}
        actual = {(path, method) for path, item in self.schema["paths"].items() for method in item}
        self.assertEqual(expected, actual)
        self.assertEqual(len(actual), 13)
        ids = []
        for path, method in actual:
            operation = self.schema["paths"][path][method]
            self.assertTrue(operation["description"])
            self.assertTrue(operation["summary"])
            self.assertTrue(operation["tags"])
            self.assertEqual(operation["security"], [{"BearerAuth": []}])
            code = "202" if method in {"post", "delete"} else "200"
            self.assertIn("schema", operation["responses"][code]["content"]["application/json"])
            self.assertIn("403", operation["responses"])
            if method in {"post", "delete"}:
                key = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
                self.assertTrue(key["required"])
                self.assertEqual(key["schema"]["minLength"], 16)
            ids.append(operation["operationId"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_documented_request_examples_pass_real_input_validation(self):
        for path, item in self.schema["paths"].items():
            operation = item.get("post", {})
            examples = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("examples", {})
            for example in examples.values():
                model = JoinRequest if path == "/v1/bots" else PlayRequest if path.endswith("/play") else ControlRequest
                model.model_validate(example["value"])
        play = self.schema["paths"]["/v1/bots/{bot_id}/play"]["post"]
        self.assertEqual(len(play["requestBody"]["content"]["application/json"]["examples"]), 5)

    def test_every_schema_reference_exists(self):
        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    current = self.schema
                    for part in value["$ref"].removeprefix("#/").split("/"):
                        current = current[part]
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(self.schema)
