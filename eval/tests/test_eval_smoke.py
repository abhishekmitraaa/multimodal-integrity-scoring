import integrity_eval


def test_package_imports() -> None:
    assert integrity_eval.__version__ == "0.0.1"
