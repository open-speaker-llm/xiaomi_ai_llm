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


def embedded_web(source=None):
    if source is None:
        source = (ROOT / 'device/native_first_client.sh').read_text()
    begin = '# BEGIN GENERATED NATIVE WEB\n'
    end = '# END GENERATED NATIVE WEB\n'
    if source.count(begin) != 1 or source.count(end) != 1:
        raise ValueError('Expected exactly one generated native web block')
    return source.split(begin, 1)[1].split(end, 1)[0]

def with_answer_audio_dependencies(names):
    """Include the shared answer lifecycle when loading individual shell entry points."""
    if {'handle_llm_dialog', 'send_text_native', 'send_text_and_play', 'route_beep_fire',
        'wait_native_live_asr'}.intersection(names):
        return tuple(dict.fromkeys((*names, 'llm_accept_feedback', 'llm_finish_answer_audio',
                                    'llm_end_beep', 'llm_answer_interrupted', 'route_beep_allowed',
                                    'native_dialog_compact')))
    return names
