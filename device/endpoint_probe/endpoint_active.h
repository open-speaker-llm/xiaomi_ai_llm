#ifndef ENDPOINT_ACTIVE_H
#define ENDPOINT_ACTIVE_H
#include <stdint.h>

/* Audio time, 10 ms frames. This is an experimental turn-end policy, not
 * semantic completion. Upload every frame, including unconfirmed speech.
 * No amplitude threshold: quiet speech is evaluated by the same VAD.
 * A pending burst delays a decision for at most 110 ms; it must reach 120 ms
 * to reset the silence clock. Isolated VAD hangover/noise cannot keep moving
 * that clock. Longer speech-like noise remains a known limitation. */
enum endpoint_reason { EP_LISTEN, EP_QUIET, EP_NO_SPEECH, EP_LIMIT, EP_INVALID };
struct endpoint_active {
    uint32_t frames, run, last_voice;
    unsigned seen;
    enum endpoint_reason reason;
};
static inline enum endpoint_reason endpoint_tick(struct endpoint_active *e,int voice) {
    if(e->reason)return e->reason;
    if(voice<0 || voice>1)return e->reason=EP_INVALID;
    e->frames++;
    if(voice) {
        e->run++;
        if(e->run>=12) {e->seen=1;e->last_voice=e->frames;}
    } else e->run=0;
    if(e->frames>=2000)return e->reason=EP_LIMIT;
    if(!e->seen && e->frames>=800)return e->reason=EP_NO_SPEECH;
    if(e->seen && e->frames-e->last_voice>=200 && !e->run)
        return e->reason=EP_QUIET;
    return EP_LISTEN;
}
static inline enum endpoint_reason endpoint_wall(const struct endpoint_active *e,uint32_t elapsed) {
    if(elapsed>=20000)return EP_LIMIT;
    if(!e->seen && elapsed>=8000)return EP_NO_SPEECH;
    return e->reason;
}
static inline const char *endpoint_reason_name(enum endpoint_reason reason) {
    switch(reason) {
    case EP_LISTEN:return "listening";
    case EP_QUIET:return "quiet";
    case EP_NO_SPEECH:return "no-speech";
    case EP_LIMIT:return "hard-limit";
    default:return "invalid-audio";
    }
}
#endif
