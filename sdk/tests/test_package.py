import retrack


def test_package_exposes_version():
    assert isinstance(retrack.__version__, str)
