/* aplay has already configured this handle for mono 24 kHz S16_LE. Run only
 * for the final EOF of a complete answer with an explicitly armed cue. */
#include <stdint.h>
#include <time.h>
#include <unistd.h>

static unsigned long long cue_now(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (unsigned long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static void cue_mark(const char *dir, const char *name) {
    char path[256];
    snprintf(path, sizeof path, "%s/marks", dir);
    FILE *file = fopen(path, "a");
    if (file) {
        fprintf(file, "%s %llu\n", name, cue_now());
        fclose(file);
    }
}

static int cue_interrupted(unsigned long long start) {
    unsigned long long stamp;
    FILE *file = fopen("/tmp/native_followup/physical-wake", "r");
    if (file) {
        int hit = fscanf(file, "%*u %llu", &stamp) == 1 && stamp > start;
        fclose(file);
        if (hit) return 1;
    }
    file = fopen("/tmp/native_first_events.log.wuw", "r");
    if (!file) return 0;
    int hit = fscanf(file, "%llu", &stamp) == 1 && stamp > start;
    fclose(file);
    return hit;
}

int snd_pcm_drain(void *pcm) {
    int (*drain)(void *) = dlsym(RTLD_NEXT, "snd_pcm_drain");
    if (!drain) return -1;
    const char *dir = getenv("NATIVE_FIRST_END_CUE_DIR");
    if (!dir || strlen(dir) > 140) return drain(pcm);

    char path[256], audio[180];
    unsigned long long start;
    snprintf(path, sizeof path, "%s/end_cue.arm", dir);
    FILE *file = fopen(path, "r");
    if (!file) return drain(pcm);
    int armed = fscanf(file, "%llu %179s", &start, audio) == 2;
    fclose(file);
    if (!armed || unlink(path)) return drain(pcm);

    int16_t samples[31200];
    file = fopen(audio, "rb");
    size_t frames = file ? fread(samples, sizeof(*samples), 31200, file) : 0;
    if (file) fclose(file);

    int rc = drain(pcm);
    if (rc < 0) return rc;
    cue_mark(dir, "answer_drain_end");
    if (!frames || cue_interrupted(start)) return rc;

    int (*prepare)(void *) = dlsym(RTLD_NEXT, "snd_pcm_prepare");
    long (*writei)(void *, const void *, unsigned long) = dlsym(RTLD_NEXT, "snd_pcm_writei");
    int (*state)(void *) = dlsym(RTLD_NEXT, "snd_pcm_state");
    int (*begin)(void *) = dlsym(RTLD_NEXT, "snd_pcm_start");
    int (*drop)(void *) = dlsym(RTLD_NEXT, "snd_pcm_drop");
    if (!prepare || !writei || !state || !begin || !drop || prepare(pcm) < 0) return rc;

    cue_mark(dir, "end_beep_start");
    snprintf(path, sizeof path, "%s/end_cue.started", dir);
    file = fopen(path, "w");
    if (file) fclose(file);
    for (size_t sent = 0; sent < frames;) {
        if (cue_interrupted(start)) {
            drop(pcm);
            return rc;
        }
        unsigned long count = frames - sent;
        if (count > 960) count = 960;
        long written = writei(pcm, samples + sent, count);
        if (written <= 0) {
            drop(pcm);
            return rc;
        }
        if (sent == 0) {
            /* PREPARED=2. Start after submitting the first 40 ms so a large
             * aplay start threshold cannot queue the full strike first. */
            if (state(pcm) == 2 && begin(pcm) < 0) {
                drop(pcm);
                return rc;
            }
            cue_mark(dir, "end_beep_audible");
        }
        sent += written;
    }
    if (drain(pcm) == 0) cue_mark(dir, "end_beep_end");
    return rc;
}
