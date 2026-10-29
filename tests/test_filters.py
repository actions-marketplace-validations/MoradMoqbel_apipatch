import unittest
from apipatch.filters import is_doc_path, is_test_path, should_ignore_path


class TestFilters(unittest.TestCase):

    def test_doc_paths(self):
        # Docs folders
        self.assertTrue(is_doc_path("docs/package.json"))
        self.assertTrue(is_doc_path("docs/quickstart.md"))
        self.assertTrue(is_doc_path("documentation/api/index.html"))
        self.assertTrue(is_doc_path("site/docusaurus.config.js"))
        self.assertTrue(is_doc_path("website/src/index.ts"))
        self.assertTrue(is_doc_path("docs"))
        self.assertTrue(is_doc_path("sub/docs/guide.md"))

        # Non-doc paths
        self.assertFalse(is_doc_path("deepeval/benchmarks/lambada/lambada.py"))
        self.assertFalse(is_doc_path("src/core/doctor.py"))
        self.assertFalse(is_doc_path("package.json"))

    def test_test_paths(self):
        # Tests folders
        self.assertTrue(is_test_path("tests/test_cli.py"))
        self.assertTrue(is_test_path("test/unit/runner.py"))
        self.assertTrue(is_test_path("src/__tests__/app.test.tsx"))
        self.assertTrue(is_test_path("e2e/login.spec.ts"))

        # Test filenames
        self.assertTrue(is_test_path("deepeval/test_metric.py"))
        self.assertTrue(is_test_path("deepeval/metric_test.py"))
        self.assertTrue(is_test_path("deepeval/metric_tests.py"))
        self.assertTrue(is_test_path("deepeval/conftest.py"))
        self.assertTrue(is_test_path("components/Button.test.js"))
        self.assertTrue(is_test_path("components/Modal.spec.ts"))

        # Non-test paths
        self.assertFalse(is_test_path("deepeval/benchmarks/lambada/lambada.py"))
        self.assertFalse(is_test_path("src/testing_utils/runner.py"))  # wait, runner.py in testing_utils
        self.assertFalse(is_test_path("src/tester.py"))

    def test_should_ignore_path(self):
        # Default ignores both
        self.assertTrue(should_ignore_path("docs/package.json"))
        self.assertTrue(should_ignore_path("tests/test_foo.py"))
        self.assertFalse(should_ignore_path("deepeval/models.py"))

        # Ignore docs only
        self.assertTrue(should_ignore_path("docs/package.json", ignore_docs=True, ignore_tests=False))
        self.assertFalse(should_ignore_path("tests/test_foo.py", ignore_docs=True, ignore_tests=False))

        # Ignore tests only
        self.assertFalse(should_ignore_path("docs/package.json", ignore_docs=False, ignore_tests=True))
        self.assertTrue(should_ignore_path("tests/test_foo.py", ignore_docs=False, ignore_tests=True))

        # Include both (ignore neither)
        self.assertFalse(should_ignore_path("docs/package.json", ignore_docs=False, ignore_tests=False, ignore_non_prod=False))
        self.assertFalse(should_ignore_path("tests/test_foo.py", ignore_docs=False, ignore_tests=False, ignore_non_prod=False))

    def test_non_prod_paths(self):
        from apipatch.filters import is_non_prod_path
        # Samples, benchmarks, tutorials, and notebooks
        self.assertTrue(is_non_prod_path("examples/basic_usage.py"))
        self.assertTrue(is_non_prod_path("samples/quickstart.ts"))
        self.assertTrue(is_non_prod_path("benchmarks/perf_test.py"))
        self.assertTrue(is_non_prod_path("tutorials/getting_started.py"))
        self.assertTrue(is_non_prod_path("demo/app.py"))
        self.assertTrue(is_non_prod_path("notebooks/analysis.ipynb"))
        self.assertTrue(is_non_prod_path("src/playground/scratch.py"))

        # Core production code
        self.assertFalse(is_non_prod_path("src/core/engine.py"))
        self.assertFalse(is_non_prod_path("apipatch/models.py"))
        self.assertFalse(is_non_prod_path("lib/client.ts"))

        # should_ignore_path ignores non-prod by default
        self.assertTrue(should_ignore_path("examples/demo.py"))
        self.assertTrue(should_ignore_path("benchmarks/runner.py"))
        self.assertFalse(should_ignore_path("examples/demo.py", ignore_non_prod=False))


if __name__ == "__main__":
    unittest.main()

