"""Offline audit of existing single-lease traces; never performs ASR or I/O to a speaker.

Text inactivity is a counterfactual candidate, NOT a production endpoint rule.
System-log ASR lines lack dialog IDs: require one software trigger, the recorded
native PID, and membership in the exact dialog's JSON snapshot. Reject ambiguous
input instead of silently attaching another conversation to the target lease.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re


def stable_candidate(updates, horizon_ms, hold_ms=2000):
    """Use arrival time, not the future final/ASR offsets. Changed text resets.

    Updates exactly at the deadline win. Missing/unchanged/empty text is not
    progress. The horizon is the observed local EOF, not an extrapolated future.
    """
    if hold_ms <= 0:
        raise ValueError('hold_ms must be positive')
    deadline, previous, last_time = None, '', -1
    for row in updates:
        t, text = row['arrival_ms'], row['text']
        if t < last_time:
            raise ValueError('arrival times must be monotonic')
        last_time = t
        if t > horizon_ms:
            break
        if deadline is not None and t > deadline:
            return {'at_ms': deadline, 'text_at_candidate': previous}
        if text and text != previous:
            previous, deadline = text, t + hold_ms
    if deadline is not None and deadline <= horizon_ms:
        return {'at_ms': deadline, 'text_at_candidate': previous}
    return None


def stamp(line, year):
    m = re.match(r'(\w+\s+\d+ \d+:\d+:\d+\.\d+)', line)
    return datetime.strptime(f'{m[1]} {year}', '%b %d %H:%M:%S.%f %Y') if m else None


def audit(folder):
    folder = Path(folder)
    state = (folder / 'state').read_text()
    fields = dict(re.findall(r'(\w+)=([^\s]+)', state))
    seq, pid, dialog = int(fields['sequence']), fields['aivs'], fields['dialog']
    probe = (folder / 'probe.log').read_text()
    triggers = re.findall(r'(\d+) pid=\d+ trigger seq=(\d+) ', probe)
    if len(triggers) != 1 or int(triggers[0][1]) != seq or 'physical wake handoff' in probe:
        raise ValueError(f'{folder}: requires one uninterrupted software lease')
    decision = re.search(r'(\d+) pid=\d+ ACTIVE decision seq=' + str(seq) +
                         r' reason=(\S+) audio_ms=(\d+) elapsed_ms=(\d+) last_voice_ms=(\d+)', probe)
    if not decision:
        raise ValueError(f'{folder}: no observed active endpoint')
    horizon = int(decision[1]) - int(triggers[0][0])
    known, offsets = set(), []
    for line in (folder / 'instructions.jsonl').read_text().splitlines():
        obj = json.loads(line)
        h = obj.get('header', {})
        if h.get('dialog_id') != dialog or h.get('namespace') != 'SpeechRecognizer' or h.get('name') != 'RecognizeResult':
            continue
        for result in obj.get('payload', {}).get('results', []):
            if result.get('text'):
                known.add(result['text'])
                if 'end_offset' in result:
                    offsets.append(result['end_offset'])
    lines = (folder / 'system.log').read_text().splitlines()
    year = int((folder / 'start').read_text().strip().split()[-1])
    wakes = [stamp(line, year) for line in lines
             if f'mipns-xiaomi[{fields["mipns"]}]' in line and 'mipns_speech.event=wakeup-1!' in line]
    if len(wakes) != 1 or not wakes[0]:
        raise ValueError(f'{folder}: missing or ambiguous wall-clock anchor')
    updates = []
    for line in lines:
        if f'mico_aivs_lab[{pid}]' not in line:
            continue
        m = re.search(r'speech_recognizer\.asr=(.*), \.final=false', line)
        if not m or not m[1]:
            continue
        t = stamp(line, year)
        if not t:
            raise ValueError('ASR line without wall clock')
        arrival = round((t - wakes[0]).total_seconds() * 1000)
        if arrival < 0 or arrival > horizon:
            continue
        if m[1] not in known:
            raise ValueError(f'{folder}: unbound ASR text or incomplete instruction snapshot')
        if not updates or m[1] != updates[-1]['text']:
            updates.append({'arrival_ms': arrival, 'text': m[1]})
    candidate = stable_candidate(updates, horizon)
    if candidate:
        later = [row for row in updates if row['arrival_ms'] > candidate['at_ms']]
        candidate['later_changed_results'] = len(later)
        candidate['ms_before_observed_eof'] = horizon - candidate['at_ms']
        candidate['classification'] = 'later_asr_progress_observed' if later else 'no_later_progress_in_observed_window'
    last_asr_offset = max(offsets) if offsets else None
    vad = []
    for mode in (1, 2, 3):
        edges = [(int(a), int(v)) for v, a in re.findall(
            r'ACTIVE edge mode=' + str(mode) + r' voice=(-?\d+) audio_ms=(\d+)', probe)]
        if not edges or edges[0][0] != 0 or any(v not in (0, 1) for _, v in edges):
            raise ValueError(f'{folder}: incomplete/invalid mode {mode} edges')
        if any(b[0] < a[0] for a, b in zip(edges, edges[1:])):
            raise ValueError('nonmonotonic audio edges')
        tail = []
        for i, (start, voice) in enumerate(edges):
            end = edges[i+1][0] if i+1 < len(edges) else int(decision[3])
            if voice and last_asr_offset is not None and end > last_asr_offset:
                tail.append([max(start, last_asr_offset), end])
        vad.append({'mode': mode, 'positive_spans_after_asr_end_offset_ms': tail})
    return {
        'trial': folder.name, 'sequence': seq, 'dialog': dialog,
        'actual_text': (folder / 'text').read_text(),
        'actual_reason': decision[2], 'actual_audio_ms': int(decision[3]),
        'actual_last_voice_ms': int(decision[5]), 'last_asr_end_offset_ms': last_asr_offset,
        'last_changed_partial_to_eof_ms': horizon-updates[-1]['arrival_ms'] if updates else None,
        'asr_updates': updates, 'stable_2s_candidate': candidate, 'vad_tail': vad,
        'limits': [
            'Counterfactual candidate only; later results do not prove when speech was audible.',
            'ASR offsets are not annotated speech; VAD tail is not labeled noise.',
            'Wall clock is anchored to matching software wake; no cross-clock precision guarantee.',
            'No decisions or outcomes after the observed endpoint are inferred.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trials', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = [audit(path) for path in args.trials]
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    for row in results:
        c = row['stable_2s_candidate']
        print(f"seq={row['sequence']} endpoint={row['actual_reason']} "
              f"last_partial_to_eof_ms={row['last_changed_partial_to_eof_ms']} "
              f"stable_2s={c['classification'] if c else 'no_candidate'}")


if __name__ == '__main__':
    main()
