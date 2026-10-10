"""按键输入功能测试：白名单、后端选择、失败映射。

命令执行器由测试注入，可执行文件检查也被替身接管，因此不真的调用任何按键工具，
测试内容只与按键输入这一功能有关。
"""

import os
import subprocess
import unittest
from unittest import mock

from py_remote_input import key_input
from py_remote_input.key_input import base

BACKENDS = ("ydotool", "wtype")


class FakeRun:
    """替代 subprocess.run：记录命令，可按需抛出异常。"""

    def __init__(self, side_effect=None):
        self.calls: list[tuple[list[str], dict]] = []
        self.side_effect = side_effect

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if self.side_effect is not None:
            raise self.side_effect
        return subprocess.CompletedProcess(command, 0, "", "")


def stub_availability(available: bool):
    return mock.patch.object(base.KeyInputBackend, "is_available", return_value=available)


class BackendSelectionTests(unittest.TestCase):
    def test_default_backend_is_ydotool(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(key_input.active_backend().name, key_input.DEFAULT_BACKEND)
            self.assertEqual(key_input.active_backend().name, "ydotool")

    def test_env_selects_backend(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                with mock.patch.dict(os.environ, {"KEY_BACKEND": backend}, clear=False):
                    self.assertEqual(key_input.active_backend().name, backend)

    def test_env_is_case_and_space_insensitive(self):
        with mock.patch.dict(os.environ, {"KEY_BACKEND": "  WType "}, clear=False):
            self.assertEqual(key_input.active_backend().name, "wtype")

    def test_unknown_backend_is_rejected(self):
        with mock.patch.dict(os.environ, {"KEY_BACKEND": "xdotool"}, clear=False):
            with self.assertRaises(key_input.UnknownKeyBackendError) as caught:
                key_input.active_backend()
            self.assertIn("xdotool", str(caught.exception))

    def test_parameter_selects_backend_and_beats_env(self):
        with mock.patch.dict(os.environ, {"KEY_BACKEND": "ydotool"}, clear=False):
            self.assertEqual(key_input.get_backend("wtype").name, "wtype")
            run = FakeRun()
            with stub_availability(True):
                result = key_input.press_key("Return", backend="wtype", run=run)
        self.assertEqual(result["method"], "wtype")
        self.assertEqual(run.calls[0][0][0], "wtype")

    def test_every_registered_backend_implements_the_interface(self):
        for name in BACKENDS:
            with self.subTest(backend=name):
                backend = key_input.BACKENDS[name]
                self.assertIsInstance(backend, base.KeyInputBackend)
                self.assertEqual(backend.name, name)
                self.assertTrue(backend.binary)
                self.assertTrue(callable(backend.build_command))


class PressKeyTests(unittest.TestCase):
    def setUp(self):
        availability = stub_availability(True)
        availability.start()
        self.addCleanup(availability.stop)

    def test_press_runs_the_selected_backend(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                run = FakeRun()
                with mock.patch.dict(os.environ, {"KEY_BACKEND": backend}, clear=False):
                    result = key_input.press_key("Return", run=run)

                self.assertEqual(len(run.calls), 1)
                command, kwargs = run.calls[0]
                self.assertEqual(command[0], backend)
                self.assertTrue(kwargs["check"])
                self.assertEqual(result["method"], backend)
                self.assertEqual(result["key"], "Return")
                self.assertIsInstance(result["durationMs"], int)

    def test_keysym_is_mapped_to_a_key_press_and_release(self):
        with mock.patch.dict(os.environ, {"KEY_BACKEND": "ydotool"}, clear=False):
            run = FakeRun()
            key_input.press_key("Return", run=run)
            command = run.calls[0][0]
        self.assertEqual(command[:2], ["ydotool", "key"])
        self.assertTrue(command[2].endswith(":1"), command)
        self.assertTrue(command[3].endswith(":0"), command)

    def test_non_whitelisted_key_is_refused_without_running_anything(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                run = FakeRun()
                with mock.patch.dict(os.environ, {"KEY_BACKEND": backend}, clear=False):
                    with self.assertRaises(ValueError):
                        key_input.press_key("Escape", run=run)
                self.assertEqual(run.calls, [])

    def test_missing_backend_binary_is_reported(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                run = FakeRun()
                with (
                    mock.patch.dict(os.environ, {"KEY_BACKEND": backend}, clear=False),
                    stub_availability(False),
                ):
                    with self.assertRaises(key_input.KeyBackendNotFoundError) as caught:
                        key_input.press_key("Return", run=run)
                self.assertIn(backend, str(caught.exception))
                self.assertEqual(run.calls, [])

    def test_backend_failure_reports_the_reason(self):
        error = subprocess.CalledProcessError(
            1, ["fake"], output="", stderr="socket /run/.ydotool_socket refused"
        )
        run = FakeRun(side_effect=error)
        with mock.patch.dict(os.environ, {"KEY_BACKEND": "ydotool"}, clear=False):
            with self.assertRaises(key_input.KeyPressFailedError) as caught:
                key_input.press_key("Return", run=run)
        message = str(caught.exception)
        self.assertIn("socket /run/.ydotool_socket refused", message)
        self.assertIn("ydotoold", message)

    def test_backend_timeout_is_reported(self):
        run = FakeRun(
            side_effect=subprocess.TimeoutExpired(["fake"], key_input.COMMAND_TIMEOUT_SECONDS)
        )
        with mock.patch.dict(os.environ, {"KEY_BACKEND": "wtype"}, clear=False):
            with self.assertRaises(key_input.KeyPressFailedError):
                key_input.press_key("Return", run=run)

    def test_press_return_uses_the_same_path_as_press_key(self):
        with mock.patch.dict(os.environ, {"KEY_BACKEND": "wtype"}, clear=False):
            run = FakeRun()
            result = key_input.press_return(run=run)
        self.assertEqual(result["key"], "Return")
        self.assertEqual(run.calls[0][0][0], "wtype")

    def test_backend_contract_is_run_on_a_stub_implementation(self):
        """接口约定：命令由子类构造，执行、返回形状与失败提示由基类负责。"""

        class StubBackend(base.KeyInputBackend):
            name = "stub"
            binary = "stub-tool"
            install_hint = "install stub-tool"
            failure_hint = " stub needs a daemon"

            def build_command(self, keysym: str) -> list[str]:
                return ["stub-tool", keysym]

        with stub_availability(True):
            run = FakeRun()
            result = StubBackend().press("Return", run=run)
        self.assertEqual(run.calls[0][0], ["stub-tool", "Return"])
        self.assertEqual(result["method"], "stub")
        self.assertEqual(result["key"], "Return")
        self.assertIsInstance(result["durationMs"], int)

        with stub_availability(False):
            with self.assertRaises(key_input.KeyBackendNotFoundError) as caught:
                StubBackend().press("Return", run=FakeRun())
        self.assertEqual(str(caught.exception), "install stub-tool")

        with stub_availability(True):
            failing = FakeRun(
                side_effect=subprocess.CalledProcessError(1, ["stub-tool"], output="", stderr="boom")
            )
            with self.assertRaises(key_input.KeyPressFailedError) as caught:
                StubBackend().press("Return", run=failing)
        message = str(caught.exception)
        self.assertIn("stub-tool", message)
        self.assertIn("boom", message)
        self.assertIn("stub needs a daemon", message)

        with stub_availability(True):
            timeout = FakeRun(side_effect=subprocess.TimeoutExpired(["stub-tool"], 5))
            with self.assertRaises(key_input.KeyPressFailedError):
                StubBackend().press("Return", run=timeout)

    def test_backend_without_command_building_is_incomplete(self):
        class Incomplete(base.KeyInputBackend):
            name = "incomplete"
            binary = "incomplete"
            install_hint = ""
            failure_hint = ""

        with self.assertRaises(TypeError):
            Incomplete()


if __name__ == "__main__":
    unittest.main()
