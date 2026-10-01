import pytest

from mirage.workspace.executor.builtins.echo import handle_echo


async def echo_bytes(args: list[str]) -> bytes:
    out, io, _ = await handle_echo(args)
    assert io.exit_code == 0
    assert isinstance(out, bytes)
    return out


@pytest.mark.asyncio
async def test_plain_words_join_with_newline():
    assert await echo_bytes(["hi", "there"]) == b"hi there\n"


@pytest.mark.asyncio
async def test_leading_n_suppresses_newline():
    assert await echo_bytes(["-n", "hi"]) == b"hi"


@pytest.mark.asyncio
async def test_trailing_n_prints_literally():
    assert await echo_bytes(["hi", "-n"]) == b"hi -n\n"


@pytest.mark.asyncio
async def test_cluster_ne():
    assert await echo_bytes(["-ne", "a\\tb"]) == b"a\tb"


@pytest.mark.asyncio
async def test_echo_hex_and_octal_escapes_name_bytes():
    assert await echo_bytes(["-ne", "\\xff"]) == b"\xff"
    assert await echo_bytes(["-ne", "\\0377"]) == b"\xff"
    assert await echo_bytes(["-ne", "\\xc3\\xa9"]) == "é".encode()


@pytest.mark.asyncio
async def test_capital_e_disables_escapes():
    assert await echo_bytes(["-e", "-E", "a\\tb"]) == b"a\\tb\n"


@pytest.mark.asyncio
async def test_e_reads_escape_as_esc():
    assert await echo_bytes(["-e", "a\\eb\\Ec"]) == b"a\x1bb\x1bc\n"


@pytest.mark.asyncio
async def test_capital_e_and_plain_echo_keep_escape_literal():
    assert await echo_bytes(["-E", "a\\eb\\Ec"]) == b"a\\eb\\Ec\n"
    assert await echo_bytes(["a\\eb\\Ec"]) == b"a\\eb\\Ec\n"


@pytest.mark.asyncio
async def test_stop_drops_the_newline():
    assert await echo_bytes(["-e", "hello\\cworld"]) == b"hello"
    assert await echo_bytes(["-e", "a\\E\\cb"]) == b"a\x1b"


@pytest.mark.asyncio
async def test_stop_ends_later_operands():
    assert await echo_bytes(["-e", "a", "b\\cc", "d"]) == b"a b"
    assert await echo_bytes(["-e", "a\\E", "\\cb"]) == b"a\x1b "


@pytest.mark.asyncio
async def test_unicode_escapes_write_utf8():
    assert (
        await echo_bytes(["-ne", "\\u00e9\\U0001F600"])
        == "é\U0001f600".encode()
    )
    assert await echo_bytes(["-ne", "\\uD800"]) == b"\xed\xa0\x80"


@pytest.mark.asyncio
async def test_last_of_e_and_E_wins_within_cluster():
    assert await echo_bytes(["-eE", "a\\tb"]) == b"a\\tb\n"
    assert await echo_bytes(["-Ee", "a\\tb"]) == b"a\tb\n"


@pytest.mark.asyncio
async def test_unknown_char_makes_word_literal():
    assert await echo_bytes(["-nq", "hi"]) == b"-nq hi\n"


@pytest.mark.asyncio
async def test_option_after_operand_is_literal():
    assert await echo_bytes(["hi", "-e", "a\\tb"]) == b"hi -e a\\tb\n"


@pytest.mark.asyncio
async def test_lone_dash_is_literal():
    assert await echo_bytes(["-"]) == b"-\n"
