#ifndef PCM_RING_H
#define PCM_RING_H
#include <stdint.h>
#define PCM_MAGIC 0x50434d31u
#define PCM_RATE 16000u
#define PCM_SAMPLES 160u
#define PCM_SLOTS 256u
#define PCM_RING_PATH "/tmp/native_followup_pcm.ring"
struct pcm_block { uint32_t sequence; int16_t samples[PCM_SAMPLES]; };
struct pcm_ring {
    uint32_t magic, version, rate, block_samples, slots, producer_pid;
    uint32_t published, errors;
    struct pcm_block blocks[PCM_SLOTS];
};
#endif
