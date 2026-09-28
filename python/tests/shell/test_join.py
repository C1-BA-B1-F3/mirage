from mirage.shell.join import shell_join


def test_leaves_safe_tokens_unquoted():
    assert shell_join(["wc", "-l", "/ram/f"]) == "wc -l /ram/f"


def test_quotes_whitespace_and_metacharacters():
    assert shell_join(["echo", "a b", "$(rm -rf /)",
                       "*.txt"]) == ("echo 'a b' '$(rm -rf /)' '*.txt'")


def test_represents_an_empty_token():
    assert shell_join(["echo", ""]) == "echo ''"


def test_writes_a_raw_byte_as_an_ansi_c_escape():
    assert shell_join(["printf", "%s",
                       "a\udcffb"]) == ("printf %s 'a'$'\\xff''b'")
    assert shell_join(["\udc80"]) == "''$'\\x80'''"


def test_leaves_a_non_ascii_character_as_itself():
    assert shell_join(["echo", "é\U00010080"]) == "echo 'é\U00010080'"
