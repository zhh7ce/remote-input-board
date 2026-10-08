import unittest
from unittest import mock

from py_remote_input import typer


class WtypeArgsTests(unittest.TestCase):
    def test_plain_text_becomes_single_argument(self):
        self.assertEqual(typer.build_wtype_args("hello 你好"), ["hello 你好"])

    def test_lf_newline_maps_to_return_keysym(self):
        self.assertEqual(
            typer.build_wtype_args("a\nb"),
            ["a", "-k", typer.RETURN_KEYSYM, "b"],
        )

    def test_crlf_newline_maps_to_single_return(self):
        self.assertEqual(
            typer.build_wtype_args("a\r\nb\r\n"),
            ["a", "-k", typer.RETURN_KEYSYM, "b", "-k", typer.RETURN_KEYSYM],
        )

    def test_multiple_blank_lines_each_press_return(self):
        self.assertEqual(
            typer.build_wtype_args("\n\n"),
            ["-k", typer.RETURN_KEYSYM, "-k", typer.RETURN_KEYSYM],
        )

    def test_batches_split_when_text_exceeds_char_limit(self):
        batches = typer.build_wtype_batches("aaa\nbb\nc", char_limit=3)

        self.assertEqual(
            batches,
            [
                ["aaa", "-k", typer.RETURN_KEYSYM],
                ["bb", "-k", typer.RETURN_KEYSYM, "c"],
            ],
        )

    def test_short_text_uses_single_batch(self):
        self.assertEqual(typer.build_wtype_batches("a\nb"), [["a", "-k", typer.RETURN_KEYSYM, "b"]])


class TypeTextTests(unittest.TestCase):
    def test_type_text_invokes_wtype_with_built_args(self):
        with (
            mock.patch.object(typer, "ensure_wtype_available", return_value="/usr/bin/wtype"),
            mock.patch.object(typer.subprocess, "run") as run,
        ):
            result = typer.type_text("a\nb")

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["wtype", "a", "-k", "Return", "b"])
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(result["method"], "wtype")
        self.assertEqual(result["charCount"], 3)

    def test_type_text_runs_one_process_per_batch(self):
        with (
            mock.patch.object(typer, "ensure_wtype_available", return_value="/usr/bin/wtype"),
            mock.patch.object(typer.subprocess, "run") as run,
            mock.patch.object(typer, "CHUNK_CHAR_LIMIT", 3),
        ):
            typer.type_text("aaa\nbbbb")

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][0], "wtype")
        self.assertEqual(run.call_args_list[1].args[0][0], "wtype")

    def test_missing_wtype_raises_clear_error(self):
        with mock.patch.object(typer.shutil, "which", return_value=None):
            with self.assertRaises(typer.WtypeNotFoundError):
                typer.type_text("hello")


if __name__ == "__main__":
    unittest.main()
