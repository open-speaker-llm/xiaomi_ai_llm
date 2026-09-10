#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Loaded only by dirac_aplay.sh in the actual PCM player process. */
__attribute__((constructor)) static void initialize_dirac(void) {
    const char *enabled = getenv("NATIVE_FIRST_DIRAC");
    if (!enabled || strcmp(enabled, "1") != 0) return;

    void *library = dlopen("/usr/lib/libDiracAPI_SHARED.so", RTLD_NOW | RTLD_GLOBAL);
    if (!library) {
        fprintf(stderr, "[DIRAC] initialization failed: library unavailable\n");
        return;
    }
    int (*initialize)(const char *) = dlsym(library, "Dirac_initialize");
    if (!initialize) {
        fprintf(stderr, "[DIRAC] initialization failed: API unavailable\n");
        return;
    }
    int rc = initialize("/data/etc/diracmobile.config");
    fprintf(stderr, "[DIRAC] initialize rc=%d config=/data/etc/diracmobile.config\n", rc);
    /* Keep the library loaded for the lifetime of aplay. ALSA owns the DSP
       instance, its volume, streaming state and teardown, as in mediaplayer. */
}
