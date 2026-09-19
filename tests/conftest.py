"""Global test safety fixtures."""

import asyncio
import inspect
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def deny_unexpected_network(respx_mock: Any) -> None:
    """Fail every HTTPX request that a test did not explicitly mock."""
    respx_mock.assert_all_mocked = True


def pytest_pyfunc_call(pyfuncitem: Any) -> bool | None:
    """Run async unit tests without adding an unapproved async-test dependency."""
    test_function = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_function):
        return None
    arguments = {
        name: pyfuncitem.funcargs[name] for name in inspect.signature(test_function).parameters
    }
    asyncio.run(test_function(**arguments))
    return True
