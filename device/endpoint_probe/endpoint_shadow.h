/* Read-only endpoint suggestions. Time is PCM sample time, never wall time.
 * A suggestion is not a command and a later voice frame is not proof that the
 * same person continued: source attribution requires the synchronized logs.
 */
#ifndef ENDPOINT_SHADOW_H
#define ENDPOINT_SHADOW_H
#include <stdint.h>
struct endpoint_shadow {
    uint32_t frames,last_voice_end_ms;
    unsigned have_voice,fired;
};
static const unsigned endpoint_gaps[3]={1200,1600,2000};
/* Bits 0..2: candidate at that gap. Bits 3..5: speech after that candidate. */
static unsigned endpoint_observe(struct endpoint_shadow *s,int voiced) {
    uint32_t end_ms=++s->frames*10u;
    if(voiced) {
        unsigned events=s->fired<<3;
        s->have_voice=1;s->last_voice_end_ms=end_ms;s->fired=0;
        return events;
    }
    unsigned events=0;
    for(unsigned i=0;i<3;i++)
        if(s->have_voice && !(s->fired&(1u<<i)) &&
           end_ms-s->last_voice_end_ms>=endpoint_gaps[i])events|=1u<<i;
    s->fired|=events;return events;
}
#endif
