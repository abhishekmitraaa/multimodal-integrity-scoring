import integrity_ml


def test_package_imports() -> None:
    assert integrity_ml.__version__ == "0.0.1"
