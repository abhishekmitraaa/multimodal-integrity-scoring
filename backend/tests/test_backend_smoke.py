import integrity_backend


def test_package_imports() -> None:
    assert integrity_backend.__version__ == "0.0.1"
