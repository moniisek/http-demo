import re
from asyncio.streams import StreamReader
from collections import namedtuple

from utils import is_empty, CRLF


class ParseError(Exception):
    def __init__(self, message):
        self.message = message


StatusLine = namedtuple("StatusLine", ['http_version', 'status_code', 'reason'])
RequestLine = namedtuple("RequestLine", ['method', 'request_target', 'http_version'])


def convert_first_line_to_bytes(line) -> bytes:
    # line is StatusLine or RequestLine
    return b" ".join(line) + b"\r\n"


def convert_headers_mapping_to_bytes(headers: dict) -> bytes:
    result = []
    for k in headers:
        result.append(bytes(f"{k}:{headers[k]}\r\n", 'utf-8'))
    return b"".join(result)


def parse_status_line(first_line: bytes) -> StatusLine:
    # specification defines syntax: (*optional)
    # HTTP-version[SP]status-code[SP]reason*
    first_line = first_line.strip(b"[\r\n]")
    groups = first_line.split(b" ", 1)
    if len(groups) < 2:
        raise ParseError("Error parsing status line - expected 2 or 3 strings separated by a single SP character.")
    try:
        protocol, http_version = groups[0].split(b"/")
    except ValueError:
        raise ParseError("Error parsing status line - expected format {protocol}/{version}")
    code_match = re.search(br'(\d{3})', groups[1])
    if code_match is None:
        raise ParseError("Invalid characters in HTTP status code")
    status_code = code_match.group()
    status_message = groups[1][code_match.end():].strip()
    if is_empty(status_message):
        status_message = None
    return StatusLine(http_version, status_code, status_message)


def parse_request_line(request_line: bytes) -> RequestLine:
    # method[SP]request-target[SP]HTTP-version
    # example: GET / HTTP/1.0
    request_line = request_line.strip(b"[\r\n]")
    groups = request_line.split(b" ")
    if len(groups) < 3:
        raise ParseError("Error parsing request line - expected 2 strings separated by a single SP character.")
    return RequestLine(*groups)


async def parse_headers(reader: StreamReader):
    raw_headers = []
    line = await reader.readuntil(CRLF)
    is_headers_end = len(line.strip(CRLF)) == 0
    while not is_headers_end:
        raw_headers.append(line)
        line = await reader.readuntil(CRLF)
        is_headers_end = len(line.strip(CRLF)) == 0

    headers_mapping = {}
    # syntax: field-name[space][:][space]value
    if len(raw_headers) == 0:
        return headers_mapping
    # might be any number of LWS around the `:` but a single space is preferred
    # LWS - linear white space (any number of spaces or \t)
    pattern = re.compile(br'(?:\s*:\s*)')
    for line in raw_headers:
        groups = re.split(pattern, line)
        if len(groups) == 2:
            # found a key-value pair
            key = groups[0].strip().lower()
            value = groups[1].strip()
            if key not in headers_mapping:
                headers_mapping[key] = [value]
            else:
                headers_mapping[key].append(value)
    return headers_mapping


async def parse_body(reader: StreamReader, headers: dict):
    # if content-length is present, it is some N -> read N bytes after the second CRLF
    # if transfer-encoding is present -> throw an exception
    # if both of these headers are missing -> continue reading until connection is closed
    # does the server always close TCP connection if it has nothing more to send?
    if b"transfer-encoding" in headers:
        raise ParseError("Header `transfer-encoding` is present!")
    content_length = None
    if b"content-length" in headers:
        content_length = int(headers[b"content-length"][0].decode())
    if content_length is not None:
        body = await reader.read(content_length)
    else:
        body = await reader.read()
    return body
