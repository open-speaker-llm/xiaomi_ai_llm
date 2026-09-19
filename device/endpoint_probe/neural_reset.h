/* Experimental reset adapter for pinned sherpa-onnx 1.10.36 + Silero v5.
 * Its Reset() leaves the input overlap buffer intact. All AcceptWaveform calls
 * must update pending. Reset between generations, never during publication.
 * Do NOT use a permanent 64-zero prefix: it changes detection on quiet speech
 * and noise. Instead, reseed with the NEXT frame's first 64 real samples, reset
 * all model/segment state again, then accept that frame's remaining 96 samples.
 * No proposals may be published from the temporary reseed inference.
 * Never append scratch data to captured/upload PCM. */
#ifndef NEURAL_RESET_H
#define NEURAL_RESET_H
#include <stdint.h>
#include <string.h>
static inline uint32_t nz_pending(uint32_t pending,uint32_t count){
    uint64_t total=(uint64_t)pending+count;
    return total<576?(uint32_t)total:64+(uint32_t)((total-64)%512);
}
static inline uint32_t nz_padding(uint32_t pending){
    return pending<576?576+(512-pending%512)%512:0;
}
/* out has room for 1088 floats, first points to at least 64 NEW samples.
 * Call Reset -> Accept(out,n) -> Reset -> Accept(first+64,remaining).
 * Track pending for every Accept; preserve it across library Reset calls. */
static inline uint32_t nz_reseed(float out[1088],uint32_t pending,const float first[64]){
    uint32_t n=nz_padding(pending);if(!n)return 0;
    memset(out,0,(n-64)*sizeof(*out));memcpy(out+n-64,first,64*sizeof(*out));
    return n;
}
#endif
