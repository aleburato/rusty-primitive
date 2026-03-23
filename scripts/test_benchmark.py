import unittest

from scripts import benchmark


class BenchmarkShapeSelectionTests(unittest.TestCase):
    def test_all_selection_includes_mixed_mode_first(self):
        selected = benchmark.parse_shape_selection("all")
        names = [name for _, name in selected]
        self.assertEqual(names[0], "Mixed")
        self.assertIn("Mixed", names)

    def test_mixed_alias_selects_combo_mode(self):
        selected = benchmark.parse_shape_selection("mixed")
        self.assertEqual(selected, [(0, "Mixed")])

    def test_build_command_uses_combo_mode_for_go_and_any_for_rust(self):
        output = benchmark.OUTPUT_DIR / "test-output.png"

        go_cmd = benchmark.build_command(
            binary="primitive-go",
            cli_style="go",
            shape_type=0,
            shape_name="Mixed",
            input_image="input.jpg",
            output_file=output,
            steps=50,
            seed=42,
        )
        rust_cmd = benchmark.build_command(
            binary="primitive-rust",
            cli_style="rust",
            shape_type=0,
            shape_name="Mixed",
            input_image="input.jpg",
            output_file=output,
            steps=50,
            seed=42,
        )

        self.assertIn("-m", go_cmd)
        self.assertEqual(go_cmd[go_cmd.index("-m") + 1], "0")
        self.assertIn("--shape", rust_cmd)
        self.assertEqual(rust_cmd[rust_cmd.index("--shape") + 1], "any")


if __name__ == "__main__":
    unittest.main()
