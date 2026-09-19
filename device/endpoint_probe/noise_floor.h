#ifndef ENDPOINT_NOISE_FLOOR_H
#define ENDPOINT_NOISE_FLOOR_H
#include <stdlib.h>
/* Experimental feature gate, not a speech recognizer. Caller selects eligible
 * background: VAD-negative frames or an ASR-delimited pre-speech prefix. Freeze
 * then, so a long utterance or a soft continuation cannot be learned away.
 * Too few frames or a zero floor fail open to the original VAD. */
struct noise_floor {
    float power[2000], reference;
    unsigned count, frozen, confident;
};
static inline int noise_power_order(const void *a,const void *b) {
    float x=*(const float *)a,y=*(const float *)b;return (x>y)-(x<y);
}
static inline void noise_observe(struct noise_floor *n,int voice,float power) {
    if(!n->frozen && !voice && power>=0 && power<1e12f && n->count<2000)
        n->power[n->count++]=power;
}
static inline void noise_freeze(struct noise_floor *n) {
    if(n->frozen)return;
    n->frozen=1;
    if(n->count<50)return; /* at least 0.5 s of VAD-negative evidence */
    qsort(n->power,n->count,sizeof(float),noise_power_order);
    n->reference=n->power[(n->count-1)*3/4];
    n->confident=n->reference>=1.0f;
}
static inline int noise_voice(const struct noise_floor *n,int original,float power,float ratio) {
    if(original!=1 || !n->confident)return original;
    return power>=n->reference*ratio;
}
#endif
