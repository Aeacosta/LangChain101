import re

# Control-character escape table for JSON strings (everything below 0x20).
_CTRL_ESCAPE = {
    '\n': '\\n',
    '\r': '\\r',
    '\t': '\\t',
    '\b': '\\b',
    '\f': '\\f',
}


def fix_json_string_control_chars(text: str) -> str:
    """Replace literal control characters inside JSON string literals with
    their valid JSON escape sequences.

    The regex matches a JSON string token (starting with an unescaped ``"``),
    capturing everything up to the closing ``"``.  Inside that span any raw
    control character is replaced with its ``\\x`` counterpart so that the
    resulting text is parseable by a standard JSON parser.
    """

    def _escape_controls_in_match(m: re.Match) -> str:
        content = m.group(1)
        result = []
        for ch in content:
            if ch in _CTRL_ESCAPE:
                result.append(_CTRL_ESCAPE[ch])
            elif ord(ch) < 0x20:
                result.append(f'\\u{ord(ch):04x}')
            else:
                result.append(ch)
        return '"' + ''.join(result) + '"'

    return re.sub(r'"((?:[^"\\]|\\.)*)\"', _escape_controls_in_match, text,
                  flags=re.DOTALL)
