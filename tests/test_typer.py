import unittest
from unittest import mock

from py_remote_input import typer


class FlattenLineBreaksTests(unittest.TestCase):
    def test_lf_becomes_single_space(self):
        self.assertEqual(typer.flatten_line_breaks("a\nb"), "a b")

    def test_crlf_and_cr_become_single_space(self):
        self.assertEqual(typer.flatten_line_breaks("a\r\nb\rc"), "a b c")

    def test_newline_runs_collapse_into_one_space(self):
        self.assertEqual(typer.flatten_line_breaks("a\n\n\nb"), "a b")

    def test_blank_text_becomes_single_space(self):
        self.assertEqual(typer.flatten_line_breaks("\n\n"), " ")


class YdotoolBatchesTests(unittest.TestCase):
    def test_plain_text_single_batch_single_argument(self):
        self.assertEqual(typer.build_ydotool_batches("hello 你好"), [["hello 你好"]])

    def test_line_breaks_never_press_enter(self):
        batches = typer.build_ydotool_batches("第一行\n第二行")

        self.assertEqual(batches, [["第一行 第二行"]])

    def test_batches_split_when_text_exceeds_char_limit(self):
        self.assertEqual(
            typer.build_ydotool_batches("aaaaa", char_limit=3),
            [["aaa"], ["aa"]],
        )

    def test_batches_split_flattened_text(self):
        self.assertEqual(
            typer.build_ydotool_batches("aaa\nbbbb", char_limit=3),
            [["aaa"], [" bb"], ["bb"]],
        )


class TypeTextTests(unittest.TestCase):
    def test_type_text_never_presses_enter(self):
        with (
            mock.patch.object(typer, "ensure_ydotool_available", return_value="/usr/bin/ydotool"),
            mock.patch.object(typer.subprocess, "run") as run,
        ):
            result = typer.type_text("a\nb")

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["ydotool", "type", "--delay", "0", "--", "a b"])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(result["method"], "ydotool")
        self.assertEqual(result["charCount"], 3)

    def test_type_text_runs_one_process_per_batch(self):
        with (
            mock.patch.object(typer, "ensure_ydotool_available", return_value="/usr/bin/ydotool"),
            mock.patch.object(typer.subprocess, "run") as run,
            mock.patch.object(typer, "CHUNK_CHAR_LIMIT", 3),
        ):
            typer.type_text("aaa\nbbbb")

        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][0], "ydotool")
            self.assertEqual(call.args[0][1], "type")

    def test_missing_ydotool_raises_clear_error(self):
        with mock.patch.object(typer.shutil, "which", return_value=None):
            with self.assertRaises(typer.YdotoolNotFoundError):
                typer.type_text("hello")

    def test_press_key_invokes_ydotool_return(self):
        with (
            mock.patch.object(typer, "ensure_ydotool_available", return_value="/usr/bin/ydotool"),
            mock.patch.object(typer.subprocess, "run") as run,
        ):
            result = typer.press_key("Return")

        self.assertEqual(run.call_args.args[0], ["ydotool", "key", "28"])
        self.assertEqual(result["key"], "Return")

    def test_press_key_rejects_non_whitelisted_keysym(self):
        with self.assertRaises(ValueError):
            typer.press_key("Escape")

    def test_press_return_helper(self):
        with (
            mock.patch.object(typer, "ensure_ydotool_available", return_value="/usr/bin/ydotool"),
            mock.patch.object(typer.subprocess, "run") as run,
        ):
            typer.press_return()

        self.assertEqual(run.call_args.args[0], ["ydotool", "key", "28"])


if __name__ == "__main__":
    unittest.main()
