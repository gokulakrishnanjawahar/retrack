import retrack_server


def test_package_exposes_version():
    assert isinstance(retrack_server.__version__, str)
