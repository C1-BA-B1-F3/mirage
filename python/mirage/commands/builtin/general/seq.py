# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import re
from dataclasses import dataclass

from mirage.accessor.base import Accessor
from mirage.commands.config import CommandOpts, command
from mirage.commands.errors import UsageError
from mirage.commands.quote import quote_text
from mirage.commands.spec import SPECS
from mirage.commands.spec.flag_view import FlagView
from mirage.commands.spec.types import CommandName
from mirage.commands.spec.usage import (
    extra_operand_error,
    missing_operand_error,
)
from mirage.io.types import ByteSource, IOResult
from mirage.types import PathSpec

# GNU seq's long_double_format: one floating directive, its flags and an
# optional L, with nothing but %% around it.
FORMAT_DIRECTIVE = re.compile(r"([-+#0 ']*)([0-9]*)(?:\.([0-9]*))?(L?)")
FLOAT_CONVERSIONS = "efgaEFGA"


@dataclass(frozen=True)
class SeqFormat:
    """A ``-f`` format GNU accepts, split around its one directive.

    Args:
        prefix (str): the text before the directive, ``%%`` kept.
        flags (str): the directive's flags.
        width (str): its field width, or empty.
        precision (str | None): its precision digits, or None.
        conversion (str): the floating conversion character.
        suffix (str): the text after the directive, ``%%`` kept.
    """

    prefix: str
    flags: str
    width: str
    precision: str | None
    conversion: str
    suffix: str


def _lone_percent(text: str) -> int:
    """Index of the first ``%`` that is not half of ``%%``, or -1.

    Args:
        text (str): the format text to scan.
    """
    i = 0
    while i < len(text):
        if text[i] == "%":
            if text[i + 1 : i + 2] != "%":
                return i
            i += 2
            continue
        i += 1
    return -1


def parse_format(fmt: str) -> SeqFormat:
    """GNU seq's ``-f`` check: exactly one floating ``%`` directive.

    Args:
        fmt (str): the format as typed.
    """
    shown = f"'{quote_text(fmt)}'"
    start = _lone_percent(fmt)
    if start < 0:
        raise UsageError(f"seq: format {shown} has no % directive", 1)
    match = FORMAT_DIRECTIVE.match(fmt, start + 1)
    end = match.end() if match else start + 1
    if end >= len(fmt):
        raise UsageError(f"seq: format {shown} ends in %", 1)
    if fmt[end] not in FLOAT_CONVERSIONS:
        raise UsageError(
            f"seq: format {shown} has unknown %{fmt[end]} directive", 1
        )
    suffix = fmt[end + 1 :]
    if _lone_percent(suffix) >= 0:
        raise UsageError(f"seq: format {shown} has too many % directives", 1)
    flags, width, precision, _ = (
        match.groups() if match else ("", "", None, "")
    )
    return SeqFormat(fmt[:start], flags, width, precision, fmt[end], suffix)


def _hex_float(value: float, upper: bool) -> str:
    mantissa, exponent = float(value).hex().split("p")
    if "." in mantissa:
        mantissa = mantissa.rstrip("0").rstrip(".")
    shown = f"{mantissa}p{exponent}"
    return shown.upper() if upper else shown


def render(spec: SeqFormat, value: float) -> str:
    """One value through a ``-f`` format, as C's printf renders it.

    Args:
        spec (SeqFormat): the parsed format.
        value (float): the value to print.
    """
    if spec.conversion in "aA":
        body = _hex_float(value, spec.conversion == "A")
    else:
        precision = "" if spec.precision is None else "." + spec.precision
        directive = "%" + spec.flags.replace("'", "") + spec.width + precision
        body = (directive + spec.conversion) % value
    return (
        spec.prefix.replace("%%", "%") + body + spec.suffix.replace("%%", "%")
    )


def _seq_generate(
    texts: list[str], separator: str, width: bool, fmt: str | None
) -> str:
    nums = [float(t) for t in texts]
    if len(nums) == 1:
        first, step, last = 1, 1, int(nums[0])
    elif len(nums) == 2:
        first, step, last = int(nums[0]), 1, int(nums[1])
    else:
        first, step, last = int(nums[0]), int(nums[1]), int(nums[2])
    values: list[int] = []
    cur = first
    if step > 0:
        while cur <= last:
            values.append(cur)
            cur += step
    elif step < 0:
        while cur >= last:
            values.append(cur)
            cur += step
    if fmt is not None:
        spec = parse_format(fmt)
        parts = [render(spec, v) for v in values]
    elif width:
        w = max((len(str(v)) for v in values), default=1)
        parts = [str(v).zfill(w) for v in values]
    else:
        parts = [str(v) for v in values]
    return separator.join(parts) + "\n"


@command("seq", vfs=None, spec=SPECS["seq"])
async def seq(
    accessor: Accessor,
    paths: list[PathSpec],
    texts: list[str],
    opts: CommandOpts,
) -> tuple[ByteSource | None, IOResult]:
    fl = FlagView(opts.flags, spec=SPECS["seq"])
    if not texts:
        raise missing_operand_error(CommandName.SEQ, None)
    if len(texts) > 3:
        raise extra_operand_error(CommandName.SEQ, texts[3])
    sep = fl.as_str("s")
    separator = sep if sep is not None else "\n"
    result = _seq_generate(texts, separator, fl.as_bool("w"), fl.as_str("f"))
    return result.encode(), IOResult()
