"""Load the deployed pure protocol block without executing client startup."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_FUNCTIONS = {'json_escape', 'json_unicode_decode', 'json_text_unescape',
                      'json_text_field', 'llm_sse_content'}


def embedded_protocol(source=None):
    if source is None:
        source = (ROOT / 'device/native_first_client.sh').read_text()
    begin = '# BEGIN GENERATED NATIVE PROTOCOL\n'
    end = '# END GENERATED NATIVE PROTOCOL\n'
    if source.count(begin) != 1 or source.count(end) != 1:
        raise ValueError('Expected exactly one generated native protocol block')
    return source.split(begin, 1)[1].split(end, 1)[0]
