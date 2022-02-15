import pydantic
import pytest

from baselooper import LooperConfig, NOPConfig


def test_extra_key_module_in_modules():
    config = LooperConfig(
        modules={
            'module': NOPConfig()
        },
        another_module=NOPConfig()
    )
    looper = config.load()
    assert 'another_module' in looper.modules


def test_extra_key_reference_in_modules():
    config = LooperConfig(
        modules={
            'module': NOPConfig()
        },
        another_module='module'
    )
    looper = config.load()
    assert 'another_module' in looper.modules


def test_extra_key_already_in_modules():
    with pytest.raises(pydantic.ValidationError):
        LooperConfig(
            modules={
                'another_module': NOPConfig(),
            },
            another_module='module'
        )


def test_missing_reference():
    with pytest.raises(pydantic.ValidationError):
        LooperConfig(
            modules={
                'module': NOPConfig(),
                'ref_name': 'ref'
            }
        )
