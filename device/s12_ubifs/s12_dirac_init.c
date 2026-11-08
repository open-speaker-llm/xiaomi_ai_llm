#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Initialize the S12's existing Dirac configuration only inside aplay. */
__attribute__((constructor)) static void initialize_dirac(void) {
    const char *enabled = getenv("NATIVE_FIRST_DIRAC");
    if (!enabled || strcmp(enabled, "1") != 0) return;
    void *lib = dlopen("/usr/lib/libDiracAPI_SHARED.so", RTLD_NOW | RTLD_GLOBAL);
    if (!lib) { fprintf(stderr, "[S12-DIRAC] dlopen failed\n"); return; }
    int (*initialize)(const char *) = dlsym(lib, "Dirac_initialize");
    if (!initialize) { fprintf(stderr, "[S12-DIRAC] symbol unavailable\n"); return; }
    int rc = initialize("/data/etc/diracmobile.config");
    fprintf(stderr, "[S12-DIRAC] initialize rc=%d\n", rc);
}
