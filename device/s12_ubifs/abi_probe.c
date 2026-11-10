/* Read-only process-local test of this S12 firmware's protobuf descriptors.
 * It sends no messages and never attaches to a native service. */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const char *name;
    uint32_t id, label, type, quantifier_offset, offset;
    const void *descriptor, *default_value;
    uint32_t flags, reserved_flags;
    void *reserved2, *reserved3;
} field_desc;
typedef struct {
    uint32_t magic;
    const char *name, *short_name, *c_name, *package_name;
    size_t size;
    unsigned n_fields;
    const field_desc *fields;
    const unsigned *fields_sorted_by_name;
    unsigned n_field_ranges;
    const void *field_ranges;
    void (*init)(void *);
    void *reserved1, *reserved2, *reserved3;
} message_desc;

static const field_desc *field(const message_desc *d, const char *name) {
    for (unsigned i = 0; i < d->n_fields; i++)
        if (strcmp(d->fields[i].name, name) == 0) return &d->fields[i];
    return NULL;
}
static int slot_ok(const message_desc *d, const field_desc *f, size_t len) {
    return f && f->offset <= d->size && len <= d->size - f->offset;
}

int main(void) {
    void *lib = dlopen("/usr/lib/libaivs-message-util.so", RTLD_NOW | RTLD_LOCAL);
    if (!lib) { fprintf(stderr, "message library unavailable\n"); return 1; }
    const message_desc *top = dlsym(lib, "speech_message__descriptor");
    const message_desc *up = dlsym(lib, "speech_message__upward_message__descriptor");
    const message_desc *prep = dlsym(lib, "speech_message__upward_message__stream_prepare_request_message__descriptor");
    size_t (*packed_size)(const void *) = dlsym(lib, "speech_message__get_packed_size");
    size_t (*pack)(const void *, void *) = dlsym(lib, "speech_message__pack");
    void *(*unpack)(void *, size_t, const void *) = dlsym(lib, "speech_message__unpack");
    void (*free_message)(void *, void *) = dlsym(lib, "speech_message__free_unpacked");
    if (!top || !up || !prep || !packed_size || !pack || !unpack || !free_message) return 2;
    if (top->size > 1024 || up->size > 1024 || prep->size > 1024 ||
        top->n_fields > 32 || up->n_fields > 32 || prep->n_fields > 32 ||
        !top->init || !up->init || !prep->init) return 3;
    const field_desc *top_type = field(top, "type"), *top_up = field(top, "upward");
    const field_desc *up_type = field(up, "type"), *up_prep = field(up, "stream_prepare_request");
    const field_desc *activate = field(prep, "activate_mode");
    if (!slot_ok(top, top_type, 4) || !slot_ok(top, top_up, sizeof(void *)) ||
        !slot_ok(up, up_type, 4) || !slot_ok(up, up_prep, sizeof(void *)) ||
        !slot_ok(prep, activate, 4)) return 4;
    unsigned char *t = calloc(1, top->size), *u = calloc(1, up->size), *p = calloc(1, prep->size);
    if (!t || !u || !p) return 5;
    top->init(t); up->init(u); prep->init(p);
    int zero = 0, one = 1;
    memcpy(t + top_type->offset, &zero, 4); memcpy(t + top_up->offset, &u, sizeof(u));
    memcpy(u + up_type->offset, &one, 4); memcpy(u + up_prep->offset, &p, sizeof(p));
    memcpy(p + activate->offset, &one, 4);
    unsigned char out[4096];
    size_t expected = packed_size(t);
    if (!expected || expected > sizeof(out)) return 6;
    size_t size = pack(t, out);
    if (size != expected) return 6;
    void *decoded = unpack(NULL, size, out), *decoded_up = NULL, *decoded_prep = NULL;
    if (!decoded) return 7;
    memcpy(&decoded_up, (unsigned char *)decoded + top_up->offset, sizeof(decoded_up));
    if (!decoded_up) return 8;
    memcpy(&decoded_prep, (unsigned char *)decoded_up + up_prep->offset, sizeof(decoded_prep));
    if (!decoded_prep) return 9;
    int value = -1;
    memcpy(&value, (unsigned char *)decoded_prep + activate->offset, 4);
    printf("S12 protobuf sizes=%zu,%zu,%zu offsets=%u,%u,%u packed=%zu activate=%d\n",
           top->size, up->size, prep->size, top_up->offset, up_prep->offset, activate->offset, size, value);
    free_message(decoded, NULL);
    free(t); free(u); free(p); dlclose(lib);
    return value == 1 ? 0 : 10;
}
