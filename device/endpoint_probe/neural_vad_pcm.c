/* Standalone saved-PCM benchmark, never loads the Xiaomi SDK or microphone.
 * Compile against the external, version-matched sherpa-onnx 1.10.36 header.
 * Every argument describes a local file. No network or automatic endpoint
 * action is implemented. Queue availability is recorded before any flush;
 * all saved samples continue through the detector to reveal later speech. */
#include <dlfcn.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>
#include "c-api-1.10.36.h"

static int16_t pcm[320000];
static double millis(clockid_t kind) {
    struct timespec t;
    if (clock_gettime(kind, &t)) exit(1);
    return t.tv_sec * 1000.0 + t.tv_nsec / 1000000.0;
}
#define LOAD(name) \
    __typeof__(&SherpaOnnx##name) name = dlsym(lib, "SherpaOnnx" #name); \
    if (!name) { fprintf(stderr, "%s\n", dlerror()); return 1; }

int main(int argc, char **argv) {
    if (argc != 5 && argc != 6) {
        fprintf(stderr, "usage: neural_vad_pcm c-api-library model pcm threshold [realtime]\n");
        return 2;
    }
    int realtime = argc == 6;
    if (realtime && strcmp(argv[5], "realtime")) return 2;
    char *end;
    float threshold = strtof(argv[4], &end);
    if (!*argv[4] || *end || !isfinite(threshold) ||
        threshold < 0.2f || threshold > 0.9f) return 2;
    FILE *input = fopen(argv[3], "rb");
    if (!input) return 1;
    /* Read bytes so a truncated final int16 is rejected as well. */
    size_t bytes = fread(pcm, 1, sizeof(pcm), input);
    int extra = fgetc(input), bad = ferror(input);
    fclose(input);
    if (!bytes || bytes % 320 || extra != EOF || bad) return 1;
    double init = millis(CLOCK_MONOTONIC);
    void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    LOAD(CreateVoiceActivityDetector);
    LOAD(DestroyVoiceActivityDetector);
    LOAD(VoiceActivityDetectorAcceptWaveform);
    LOAD(VoiceActivityDetectorDetected);
    LOAD(VoiceActivityDetectorEmpty);
    LOAD(VoiceActivityDetectorFront);
    LOAD(VoiceActivityDetectorPop);
    LOAD(DestroySpeechSegment);
    SherpaOnnxVadModelConfig config = {0};
    config.silero_vad.model = argv[2];
    config.silero_vad.threshold = threshold;
    config.silero_vad.min_silence_duration = 2.0f;
    config.silero_vad.min_speech_duration = 0.12f;
    config.silero_vad.max_speech_duration = 30.0f;
    config.silero_vad.window_size = 512;
    config.sample_rate = 16000;
    config.num_threads = 1;
    config.provider = "cpu";
    SherpaOnnxVoiceActivityDetector *vad = CreateVoiceActivityDetector(&config, 25.0f);
    if (!vad) return 1;
    double init_ms = millis(CLOCK_MONOTONIC) - init;
    double cpu = millis(CLOCK_PROCESS_CPUTIME_ID);
    double wall = millis(CLOCK_MONOTONIC), max_step = 0;
    double max_lag = 0;
    unsigned late_frames = 0;
    unsigned frames = (unsigned)(bytes / 320), segments = 0;
    int previous = 0;
    for (unsigned i = 0; i < frames; i++) {
        double available = wall + (i + 1) * 10.0;
        if (realtime) {
            struct timespec target = {(time_t)(available / 1000.0), 0};
            target.tv_nsec = (long)((available - target.tv_sec * 1000.0) * 1000000.0);
            int rc;
            do { rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &target, NULL); }
            while (rc == EINTR);
            if (rc) return 1;
        }
        float samples[160];
        for (unsigned j = 0; j < 160; j++) samples[j] = pcm[i * 160 + j] / 32768.0f;
        double step = millis(CLOCK_MONOTONIC);
        VoiceActivityDetectorAcceptWaveform(vad, samples, 160);
        step = millis(CLOCK_MONOTONIC) - step;
        if (step > max_step) max_step = step;
        if (realtime) {
            double lag = millis(CLOCK_MONOTONIC) - available;
            if (lag > max_lag) max_lag = lag;
            if (lag > 10.0) late_frames++;
        }
        int detected = VoiceActivityDetectorDetected(vad);
        if (detected != previous) {
            printf("edge available_ms=%u detected=%d\n", (i + 1) * 10, detected);
            previous = detected;
        }
        while (!VoiceActivityDetectorEmpty(vad)) {
            const SherpaOnnxSpeechSegment *s = VoiceActivityDetectorFront(vad);
            if (!s) return 1;
            printf("segment available_ms=%u start_ms=%.3f end_ms=%.3f\n",
                   (i + 1) * 10, s->start / 16.0, (s->start + s->n) / 16.0);
            DestroySpeechSegment(s);
            VoiceActivityDetectorPop(vad);
            segments++;
        }
    }
    cpu = millis(CLOCK_PROCESS_CPUTIME_ID) - cpu;
    wall = millis(CLOCK_MONOTONIC) - wall;
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage)) return 1;
    printf("summary threshold=%.2f audio_ms=%u segments=%u open_speech=%d "
           "init_ms=%.3f cpu_ms=%.3f wall_ms=%.3f max_step_ms=%.3f maxrss_kib=%ld "
           "realtime=%d max_input_age_ms=%.3f over_10ms_frames=%u\n",
           threshold, frames * 10, segments, previous, init_ms, cpu, wall,
           max_step, usage.ru_maxrss, realtime, max_lag, late_frames);
    /* Flush would fabricate a terminal event from file EOF. Never call it. */
    DestroyVoiceActivityDetector(vad);
    dlclose(lib);
    return 0;
}
