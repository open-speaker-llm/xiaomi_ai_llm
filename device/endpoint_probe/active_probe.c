/* Opt-in diagnostic build only. Modes 4/5 use live device VAD and local EOF;
 * mode 4 feeds a recorded question, mode 5 forwards the original microphone.
 * Mode 6 forwards the microphone into an exact-lease, read-only neural
 * observer and ends at a fixed 24 seconds, never at a neural candidate.
 * Mode 7 lets the native controller validate a separate, fresh, caught-up
 * neural proposal before local EOF; the same fixed cap remains as fallback.
 * The existing ASR-only lease supplies verified sequence/owner/dialog binding.
 * Physical first-turn NLP integration is deliberately a separate next step. */
#define PROBE_ACTIVE_ENDPOINT
#include "protocol_probe.c"
