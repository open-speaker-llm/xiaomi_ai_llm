#ifndef ENDPOINT_CAPTURE_BUFFER_H
#define ENDPOINT_CAPTURE_BUFFER_H
#include <stdint.h>
#include <string.h>
/* Optional diagnostic copy of the exact ASR callback, 16 kHz mono S16LE.
 * No allocation or filesystem I/O on the microphone callback. Caller holds
 * replay_lock and checks ownership. Default microphone trials never enable it.
 */
#define CAPTURE_BYTES (20u * 32000u)
struct capture_buffer {
    unsigned enabled, used;
    unsigned char pcm[CAPTURE_BYTES];
};
static inline void capture_reset(struct capture_buffer *c,unsigned enabled) {
    memset(c,0,sizeof(*c));c->enabled=enabled;
}
static inline void capture_append(struct capture_buffer *c,const void *pcm,unsigned length) {
    if(!c->enabled || !length || length%320)return;
    unsigned count=CAPTURE_BYTES-c->used;
    if(count>length)count=length;
    memcpy(c->pcm+c->used,pcm,count);c->used+=count;
}
#endif
